from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    DetectedChange,
    Lesson,
    LessonRevision,
    LessonStatus,
    ScheduleSnapshot,
    StudentGroup,
)
from app.schedule.diff import LessonChange, compare_schedules, pair_lessons
from app.schedule.normalizer import NormalizedLesson, normalize_schedule
from app.schedule.spbu_client import SpbuTimetableClient


@dataclass(frozen=True, slots=True)
class SyncResult:
    group: StudentGroup
    snapshot: ScheduleSnapshot
    changes: tuple[LessonChange, ...]
    created_snapshot: bool


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _lesson_from_revision(
    group_source_id: int,
    revision: LessonRevision,
) -> NormalizedLesson:
    return NormalizedLesson(
        group_source_id=group_source_id,
        starts_at=revision.starts_at,
        ends_at=revision.ends_at,
        subject=revision.subject,
        subject_normalized=revision.subject_normalized,
        activity_type=revision.activity_type,
        delivery_mode=revision.delivery_mode,
        location_text=revision.location_text,
        building_alias=revision.building_alias,
        room=revision.room,
        teacher_names=tuple(revision.teacher_names),
        is_cancelled=revision.is_cancelled,
        source_marked_time_changed=revision.source_marked_time_changed,
        source_marked_location_changed=revision.source_marked_location_changed,
        source_marked_teacher_changed=revision.source_marked_teacher_changed,
        source_payload=revision.source_payload,
    )


def _revision(
    lesson: Lesson,
    snapshot: ScheduleSnapshot,
    normalized: NormalizedLesson,
    observed_at: datetime,
) -> LessonRevision:
    return LessonRevision(
        id=uuid.uuid4(),
        lesson=lesson,
        snapshot=snapshot,
        observed_at=observed_at,
        starts_at=normalized.starts_at,
        ends_at=normalized.ends_at,
        subject=normalized.subject,
        subject_normalized=normalized.subject_normalized,
        activity_type=normalized.activity_type,
        delivery_mode=normalized.delivery_mode,
        location_text=normalized.location_text,
        building_alias=normalized.building_alias,
        room=normalized.room,
        teacher_names=list(normalized.teacher_names),
        is_cancelled=normalized.is_cancelled,
        source_marked_time_changed=normalized.source_marked_time_changed,
        source_marked_location_changed=normalized.source_marked_location_changed,
        source_marked_teacher_changed=normalized.source_marked_teacher_changed,
        source_payload=normalized.source_payload,
    )


def _change_key(lesson_id: uuid.UUID, change: LessonChange) -> str:
    payload = {
        "lesson_id": str(lesson_id),
        "kind": change.kind.value,
        "before": change.before.comparable_payload() if change.before else None,
        "after": change.after.comparable_payload() if change.after else None,
    }
    return _canonical_hash(payload)


async def _get_or_create_group(
    session: AsyncSession,
    source_id: int,
    display_name: str,
    observed_at: datetime,
) -> StudentGroup:
    group = await session.scalar(
        select(StudentGroup).where(StudentGroup.source_id == source_id)
    )
    if group is None:
        group = StudentGroup(
            id=uuid.uuid4(),
            source_id=source_id,
            display_name=display_name,
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(group)
    else:
        group.display_name = display_name
        group.updated_at = observed_at
    return group


async def sync_group_week(
    session: AsyncSession,
    client: SpbuTimetableClient,
    group_source_id: int,
    range_start: date,
    range_end: date,
    *,
    observed_at: datetime | None = None,
) -> SyncResult:
    """Fetch and persist one range, normally an ISO week (Monday through Sunday).

    The first observation creates the baseline without producing user-facing changes.
    Later observations preserve every source state and create deduplicated changes.
    The caller owns the transaction and decides when to commit.
    """

    observed_at = observed_at or datetime.now(UTC)
    response = await client.fetch_group_schedule(
        group_source_id, range_start, range_end
    )
    raw_payload = response.model_dump(by_alias=True, mode="json")
    source_hash = _canonical_hash(raw_payload)
    current = normalize_schedule(response)

    group = await _get_or_create_group(
        session,
        response.group_id,
        response.group_display_name,
        observed_at,
    )
    await session.flush()

    latest = await session.scalar(
        select(ScheduleSnapshot)
        .where(
            ScheduleSnapshot.group_id == group.id,
            ScheduleSnapshot.range_start == range_start,
            ScheduleSnapshot.range_end == range_end,
        )
        .order_by(ScheduleSnapshot.fetched_at.desc())
        .options(
            selectinload(ScheduleSnapshot.revisions).selectinload(LessonRevision.lesson)
        )
        .limit(1)
    )

    if latest is not None and latest.source_hash == source_hash:
        latest.fetched_at = observed_at
        await session.flush()
        return SyncResult(group, latest, (), False)

    snapshot = ScheduleSnapshot(
        id=uuid.uuid4(),
        group=group,
        range_start=range_start,
        range_end=range_end,
        fetched_at=observed_at,
        source_hash=source_hash,
        raw_payload=raw_payload,
    )
    session.add(snapshot)

    if latest is None:
        for normalized in current:
            lesson = Lesson(
                id=uuid.uuid4(),
                group=group,
                status=(
                    LessonStatus.cancelled
                    if normalized.is_cancelled
                    else LessonStatus.active
                ),
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            session.add(_revision(lesson, snapshot, normalized, observed_at))
        await session.flush()
        return SyncResult(group, snapshot, (), True)

    previous_revisions = sorted(
        latest.revisions,
        key=lambda item: (item.starts_at, item.subject_normalized, str(item.lesson_id)),
    )
    previous = [
        _lesson_from_revision(group_source_id, revision)
        for revision in previous_revisions
    ]
    lesson_by_previous_id = {
        id(normalized): revision.lesson
        for normalized, revision in zip(previous, previous_revisions, strict=True)
    }

    pairs, removed, added = pair_lessons(previous, current)
    lesson_by_current_id: dict[int, Lesson] = {}

    for before, after in pairs:
        lesson = lesson_by_previous_id[id(before)]
        lesson.status = (
            LessonStatus.cancelled if after.is_cancelled else LessonStatus.active
        )
        lesson.last_seen_at = observed_at
        session.add(_revision(lesson, snapshot, after, observed_at))
        lesson_by_current_id[id(after)] = lesson

    for before in removed:
        lesson_by_previous_id[id(before)].status = LessonStatus.removed

    for after in added:
        lesson = Lesson(
            id=uuid.uuid4(),
            group=group,
            status=LessonStatus.cancelled
            if after.is_cancelled
            else LessonStatus.active,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        session.add(_revision(lesson, snapshot, after, observed_at))
        lesson_by_current_id[id(after)] = lesson

    await session.flush()

    changes = compare_schedules(previous, current)
    for change in changes:
        if change.after is not None:
            lesson = lesson_by_current_id[id(change.after)]
        else:
            lesson = lesson_by_previous_id[id(change.before)]  # type: ignore[arg-type]
        session.add(
            DetectedChange(
                id=uuid.uuid4(),
                lesson_id=lesson.id,
                kind=change.kind,
                detected_at=observed_at,
                deduplication_key=_change_key(lesson.id, change),
                before_payload=(
                    change.before.comparable_payload() if change.before else None
                ),
                after_payload=change.after.comparable_payload()
                if change.after
                else None,
                message=change.message,
            )
        )

    await session.flush()
    return SyncResult(group, snapshot, tuple(changes), True)
