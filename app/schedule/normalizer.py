from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.database.models import ActivityType, DeliveryMode
from app.schedule.source_models import GroupScheduleResponse, StudyEvent


@dataclass(frozen=True, slots=True)
class NormalizedLesson:
    group_source_id: int
    starts_at: datetime
    ends_at: datetime
    subject: str
    subject_normalized: str
    activity_type: ActivityType
    delivery_mode: DeliveryMode
    location_text: str | None
    building_alias: str | None
    room: str | None
    teacher_names: tuple[str, ...]
    is_cancelled: bool
    source_marked_time_changed: bool
    source_marked_location_changed: bool
    source_marked_teacher_changed: bool
    source_payload: dict[str, Any]

    def comparable_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["activity_type"] = self.activity_type.value
        payload["delivery_mode"] = self.delivery_mode.value
        payload["starts_at"] = self.starts_at.isoformat()
        payload["ends_at"] = self.ends_at.isoformat()
        payload["teacher_names"] = list(self.teacher_names)
        payload.pop("source_payload")
        return payload


_ACTIVITY_SUFFIXES: tuple[tuple[tuple[str, ...], ActivityType], ...] = (
    (
        ("лабораторная работа", "лабораторное занятие", "laboratory class", "lab"),
        ActivityType.laboratory,
    ),
    (
        ("практическое занятие", "практика", "practical class", "practice"),
        ActivityType.practical,
    ),
    (("семинар", "seminar"), ActivityType.seminar),
    (("лекция", "lecture"), ActivityType.lecture),
    (("консультация", "consultation"), ActivityType.consultation),
    (
        (
            "контрольная работа",
            "зачет",
            "зачёт",
            "экзамен",
            "аттестация",
            "test",
            "exam",
        ),
        ActivityType.assessment,
    ),
)

_BUILDING_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"университетск(?:ий|ого)\s+проспект[^\d]*28\b", re.IGNORECASE),
        "МАТМЕХ",
    ),
    (
        re.compile(r"университетск(?:ий|ого)\s+проспект[^\d]*35\b", re.IGNORECASE),
        "ПМ-ПУ",
    ),
)
_SPBU_TIMEZONE = ZoneInfo("Europe/Moscow")


def _spbu_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_SPBU_TIMEZONE)
    return value.astimezone(_SPBU_TIMEZONE)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized).strip(" ,.;")


def split_subject_and_activity(subject: str) -> tuple[str, ActivityType]:
    clean = re.sub(r"\s+", " ", subject).strip(" ,")
    folded = normalize_text(clean)
    for suffixes, activity_type in _ACTIVITY_SUFFIXES:
        for suffix in suffixes:
            suffix_folded = normalize_text(suffix)
            if folded == suffix_folded:
                return clean, activity_type
            if folded.endswith(", " + suffix_folded):
                return clean[: -(len(suffix) + 2)].rstrip(" ,"), activity_type
    return clean, ActivityType.other


def detect_delivery_mode(location_text: str) -> DeliveryMode:
    folded = normalize_text(location_text)
    if not folded:
        return DeliveryMode.unknown

    online_markers = (
        "онлайн",
        "online",
        "дистанцион",
        "информационно-коммуникационных технологий",
    )
    offline_markers = ("университетский проспект", "аудит", "корпус", "лит.")
    has_online = any(marker in folded for marker in online_markers)
    has_offline = any(marker in folded for marker in offline_markers)

    if has_online and has_offline:
        return DeliveryMode.hybrid
    if has_online:
        return DeliveryMode.online
    return DeliveryMode.offline


def detect_building_alias(location_text: str) -> str | None:
    for pattern, alias in _BUILDING_ALIASES:
        if pattern.search(location_text):
            return alias
    return None


def extract_room(location_text: str, delivery_mode: DeliveryMode) -> str | None:
    if delivery_mode == DeliveryMode.online:
        return None
    parts = [part.strip() for part in location_text.split(",") if part.strip()]
    if not parts:
        return None
    candidate = parts[-1]
    if re.search(r"\d", candidate) and not re.match(
        r"^(д\.|дом)\s*\d", candidate, re.I
    ):
        return re.sub(r"^(ауд(?:итория)?\.?\s*)", "", candidate, flags=re.I).strip()
    return None


def extract_teacher_names(event: StudyEvent) -> tuple[str, ...]:
    refs = event.educators or [
        ref for location in event.event_locations for ref in location.educators
    ]
    if refs:
        names = [ref.display_name.strip() for ref in refs if ref.display_name.strip()]
    else:
        names = [
            name.strip()
            for name in event.educators_display_text.split(";")
            if name.strip()
        ]
    return tuple(dict.fromkeys(names))


def normalize_event(group_source_id: int, event: StudyEvent) -> NormalizedLesson:
    subject, activity_type = split_subject_and_activity(event.subject)
    location_text = event.locations_display_text.strip() or None
    delivery_mode = detect_delivery_mode(location_text or "")
    return NormalizedLesson(
        group_source_id=group_source_id,
        starts_at=_spbu_datetime(event.start),
        ends_at=_spbu_datetime(event.end),
        subject=subject,
        subject_normalized=normalize_text(subject),
        activity_type=activity_type,
        delivery_mode=delivery_mode,
        location_text=location_text,
        building_alias=detect_building_alias(location_text or ""),
        room=extract_room(location_text or "", delivery_mode),
        teacher_names=extract_teacher_names(event),
        is_cancelled=event.is_cancelled,
        source_marked_time_changed=event.time_was_changed,
        source_marked_location_changed=event.locations_were_changed,
        source_marked_teacher_changed=event.educators_were_reassigned,
        source_payload=event.model_dump(by_alias=True, mode="json"),
    )


def normalize_schedule(response: GroupScheduleResponse) -> list[NormalizedLesson]:
    lessons = [
        normalize_event(response.group_id, event)
        for day in response.days
        for event in day.events
    ]
    return sorted(
        lessons,
        key=lambda item: (
            item.starts_at,
            item.subject_normalized,
            item.location_text or "",
            item.teacher_names,
        ),
    )
