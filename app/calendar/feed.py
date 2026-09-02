from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from urllib.parse import quote

from app.database.models import ActivityType, DeliveryMode
from app.telegram.types import GroupOption, ScheduleLesson


@dataclass(frozen=True, slots=True)
class CalendarKind:
    slug: str
    name: str
    suggested_color: str
    apple_color: str


CALENDAR_KINDS: tuple[CalendarKind, ...] = (
    CalendarKind("lecture", "СПбГУ · Лекции", "коралловый", "#FF6B6B"),
    CalendarKind("practical", "СПбГУ · Практики", "синий", "#4D96FF"),
    CalendarKind("seminar", "СПбГУ · Семинары", "зелёный", "#6BCB77"),
    CalendarKind("laboratory", "СПбГУ · Лабораторные", "фиолетовый", "#9D7BFF"),
    CalendarKind("other", "СПбГУ · Другие занятия", "оранжевый", "#FFB84D"),
    CalendarKind("cancelled", "СПбГУ · Отменённые", "серый", "#8E8E93"),
)
VALID_KINDS = {item.slug for item in CALENDAR_KINDS}

_ACTIVITY_LABELS = {
    ActivityType.lecture: "Лекция",
    ActivityType.practical: "Практика",
    ActivityType.seminar: "Семинар",
    ActivityType.laboratory: "Лабораторная",
    ActivityType.consultation: "Консультация",
    ActivityType.assessment: "Контроль",
    ActivityType.other: "Занятие",
}
_DELIVERY_LABELS = {
    DeliveryMode.offline: "🏛 Очно",
    DeliveryMode.online: "💻 Онлайн",
    DeliveryMode.hybrid: "🌐 Очно или онлайн",
    DeliveryMode.unknown: "Формат не указан",
}


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold(line: str) -> list[str]:
    chunks: list[str] = []
    remaining = line
    while len(remaining.encode()) > 73:
        index = min(73, len(remaining))
        while len(remaining[:index].encode()) > 73:
            index -= 1
        chunks.append(remaining[:index])
        remaining = " " + remaining[index:]
    chunks.append(remaining)
    return chunks


def _kind_matches(kind: str, lesson: ScheduleLesson) -> bool:
    if kind == "cancelled":
        return lesson.is_cancelled
    if lesson.is_cancelled:
        return False
    if kind == "other":
        return lesson.activity_type in {
            ActivityType.consultation,
            ActivityType.assessment,
            ActivityType.other,
        }
    return lesson.activity_type.value == kind


def build_icalendar(
    kind: str,
    group: GroupOption,
    lessons: tuple[ScheduleLesson, ...],
    *,
    base_url: str,
) -> str:
    calendar_kind = next((item for item in CALENDAR_KINDS if item.slug == kind), None)
    if calendar_kind is None:
        raise ValueError("Unknown calendar kind")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SPbU Assistant//Timetable RU//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_kind.name)}",
        f"X-APPLE-CALENDAR-COLOR:{calendar_kind.apple_color}",
        "X-PUBLISHED-TTL:PT10M",
        "REFRESH-INTERVAL;VALUE=DURATION:PT10M",
    ]
    for lesson in lessons:
        if not _kind_matches(kind, lesson):
            continue
        summary = ("❌ " if lesson.is_cancelled else "") + lesson.subject
        location = lesson.location_text or lesson.building_alias or ""
        description_parts = [
            _ACTIVITY_LABELS[lesson.activity_type],
            _DELIVERY_LABELS[lesson.delivery_mode],
        ]
        if lesson.teacher_names:
            description_parts.append(
                "Преподаватель: " + "; ".join(lesson.teacher_names)
            )
        if lesson.building_alias and lesson.room:
            description_parts.append(f"{lesson.building_alias}, ауд. {lesson.room}")
        elif location:
            description_parts.append(location)
        source_url = (
            f"{base_url.rstrip('/')}/AMCP/StudentGroupEvents/Primary/"
            f"{group.source_id}/{lesson.starts_at:%Y-%m-%d}"
        )
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:{lesson.lesson_id}@spbu-assistant",
                f"DTSTAMP:{lesson.observed_at.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                f"LAST-MODIFIED:{lesson.observed_at.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                f"SEQUENCE:{int(lesson.observed_at.timestamp())}",
                f"DTSTART:{lesson.starts_at.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                f"DTEND:{lesson.ends_at.astimezone(UTC):%Y%m%dT%H%M%SZ}",
                f"SUMMARY:{_escape(summary)}",
                f"DESCRIPTION:{_escape(chr(10).join(description_parts))}",
                f"LOCATION:{_escape(location)}",
                f"URL:{source_url}",
                f"CATEGORIES:{_escape(_ACTIVITY_LABELS[lesson.activity_type])}",
                "STATUS:CANCELLED" if lesson.is_cancelled else "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT" if lesson.is_cancelled else "TRANSP:OPAQUE",
                "END:VEVENT",
            )
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def calendar_setup_html(token: str, public_base_url: str) -> str:
    base = public_base_url.rstrip("/")
    cards = []
    for kind in CALENDAR_KINDS:
        https_url = f"{base}/calendar/{token}/{kind.slug}.ics"
        webcal_url = "webcal://" + https_url.split("://", 1)[-1]
        cards.append(
            f'<li><a href="{webcal_url}">{kind.name}</a> '
            f"<small>цвет: {kind.suggested_color}</small></li>"
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>Apple Calendar · СПбГУ</title>
<style>
body{{font:17px -apple-system,BlinkMacSystemFont,sans-serif;max-width:680px;
margin:40px auto;padding:0 20px;line-height:1.45}}
li{{margin:14px 0}}a{{color:#1769e0}}small{{color:#666}}
</style>
</head><body><h1>Календари СПбГУ</h1>
<p>Добавьте нужные календари отдельно — тогда каждому можно назначить свой цвет
в Apple Calendar.</p>
<ul>{"".join(cards)}</ul>
<h2>Как удалить</h2>
<p><b>iPhone:</b> Календарь → Календари → ⓘ рядом с календарём → Удалить календарь.</p>
<p><b>Mac:</b> нажмите календарь правой кнопкой в боковой панели → Отписаться.</p>
<p>Кнопка «Отключить Apple Calendar» в Telegram отзовёт ссылку на сервере,
но удалить подписку с устройства Apple может только владелец устройства.</p>
</body></html>"""


def google_calendar_setup_html(token: str, public_base_url: str) -> str:
    base = public_base_url.rstrip("/")
    cards = []
    for kind in CALENDAR_KINDS:
        feed_url = f"{base}/calendar/{token}/{kind.slug}.ics"
        google_url = "https://calendar.google.com/calendar/render?cid=" + quote(
            feed_url,
            safe="",
        )
        cards.append(
            f'<li><a class="button" href="{google_url}" target="_blank" '
            'rel="noreferrer">'
            f"Добавить: {kind.name}</a><br><small>Рекомендуемый цвет: "
            f"{kind.suggested_color}</small><details><summary>"
            "Ссылка для ручного добавления"
            f"</summary><code>{feed_url}</code></details></li>"
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>Google Calendar · СПбГУ</title>
<style>
body{{font:17px -apple-system,BlinkMacSystemFont,sans-serif;max-width:720px;
margin:40px auto;padding:0 20px;line-height:1.45;color:#202124}}
li{{margin:20px 0}}.button{{display:inline-block;background:#1a73e8;color:white;
padding:10px 14px;border-radius:8px;text-decoration:none}}small{{color:#666}}
details{{margin-top:8px}}code{{display:block;overflow-wrap:anywhere;background:#f4f5f7;
padding:8px;border-radius:6px;margin-top:6px}}
</style></head><body><h1>Google Calendar · СПбГУ</h1>
<p>Добавьте нужные типы занятий. Они разделены, чтобы в Google Calendar можно было
назначить им разные цвета.</p><ul>{"".join(cards)}</ul>
<h2>Если кнопка не сработала</h2>
<p>Откройте Google Calendar на компьютере → «Другие календари» → «+» →
«Добавить по URL» и вставьте ссылку из нужного блока выше.</p>
<h2>Как удалить</h2><p>Google Calendar → наведите курсор на календарь → ⋮ →
«Настройки и общий доступ» → «Удалить календарь» → «Отказаться от подписки».</p>
<p><small>Обновления расписания публикуются ботом автоматически. Когда они появятся
в приложении, решает Google Calendar.</small></p></body></html>"""
