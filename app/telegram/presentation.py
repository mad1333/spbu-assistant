from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date
from html import escape

from app.database.models import ActivityType, DeliveryMode, DisplayMode
from app.schedule.normalizer import NormalizedLesson, normalize_text
from app.schedule.source_models import EducatorScheduleResponse
from app.telegram.types import GroupOption, ScheduleLesson, UserContext

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
ACTIVITY = {
    ActivityType.lecture: ("📕", "Лекция"),
    ActivityType.practical: ("📘", "Практика"),
    ActivityType.seminar: ("📗", "Семинар"),
    ActivityType.laboratory: ("🧪", "Лабораторная"),
    ActivityType.consultation: ("💬", "Консультация"),
    ActivityType.assessment: ("📝", "Контроль"),
    ActivityType.other: ("📒", "Занятие"),
}
DELIVERY = {
    DeliveryMode.offline: ("🏛", "Очно"),
    DeliveryMode.online: ("💻", "Онлайн"),
    DeliveryMode.hybrid: ("🌐", "Очно или онлайн"),
    DeliveryMode.unknown: ("📍", "Формат не указан"),
}


def russian_date(value: date, *, include_year: bool = False) -> str:
    suffix = f" {value.year}" if include_year else ""
    return f"{WEEKDAYS[value.weekday()]}, {value.day} {MONTHS[value.month - 1]}{suffix}"


def activity_short(lesson: ScheduleLesson) -> str:
    emoji, label = ACTIVITY[lesson.activity_type]
    return f"{emoji} {label}"


def lesson_button_text(lesson: ScheduleLesson) -> str:
    cancelled = "❌ " if lesson.is_cancelled else ""
    emoji, label = ACTIVITY[lesson.activity_type]
    subject = lesson.subject if len(lesson.subject) <= 30 else lesson.subject[:29] + "…"
    return f"{cancelled}{lesson.starts_at:%H:%M} · {emoji} {label} · {subject}"


def is_english_subgroup(lesson: ScheduleLesson) -> bool:
    subject = normalize_text(lesson.subject)
    return "английский язык" in subject and "траектория" in subject


def english_subgroup_key(lesson: ScheduleLesson) -> str:
    return english_subgroup_key_parts(lesson.subject, lesson.teacher_names)


def english_subgroup_key_parts(subject: str, teacher_names: tuple[str, ...]) -> str:
    teacher = teacher_names[0] if teacher_names else "без преподавателя"
    value = f"{normalize_text(subject)}|{normalize_text(teacher)}"
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def english_subgroup_label(lesson: ScheduleLesson) -> str:
    teacher = (
        lesson.teacher_names[0] if lesson.teacher_names else "преподаватель не указан"
    )
    return f"{lesson.subject} · {teacher}"


def english_subgroup_choice_matches(
    subject: str,
    teacher_names: tuple[str, ...],
    weekday: int,
    selected_key: str,
    group_source_id: int,
) -> bool:
    if english_subgroup_key_parts(subject, teacher_names) != selected_key:
        return False
    teacher = normalize_text(teacher_names[0]) if teacher_names else ""
    if group_source_id == 474999 and "костюшина ж. т" in teacher:
        return weekday == 2
    return True


def apply_english_subgroup(
    lessons: tuple[ScheduleLesson, ...],
    selected_key: str | None,
    group_source_id: int,
) -> tuple[ScheduleLesson, ...]:
    if selected_key is None:
        return lessons
    subgroup_lessons = [lesson for lesson in lessons if is_english_subgroup(lesson)]
    if not subgroup_lessons:
        return lessons
    selected = {
        lesson.lesson_id
        for lesson in subgroup_lessons
        if english_subgroup_choice_matches(
            lesson.subject,
            lesson.teacher_names,
            lesson.starts_at.weekday(),
            selected_key,
            group_source_id,
        )
    }
    if not selected:
        return tuple(lesson for lesson in lessons if not is_english_subgroup(lesson))
    return tuple(
        lesson
        for lesson in lessons
        if not is_english_subgroup(lesson) or lesson.lesson_id in selected
    )


def _location(lesson: ScheduleLesson) -> str | None:
    if lesson.building_alias and lesson.room:
        return f"{lesson.building_alias} · ауд. {lesson.room}"
    if lesson.building_alias:
        return lesson.building_alias
    return lesson.location_text


def format_day(
    target: date,
    group: GroupOption,
    lessons: tuple[ScheduleLesson, ...],
    user: UserContext,
    *,
    today: date,
) -> str:
    title = "Сегодня" if target == today else russian_date(target)
    lines = [f"📅 <b>{escape(title)}</b>", f"Группа {escape(group.display_name)}", ""]
    if not lessons:
        lines.append("Занятий нет ✨")
        return "\n".join(lines)

    for item in lessons:
        emoji, activity = ACTIVITY[item.activity_type]
        subject = escape(item.subject)
        if item.is_cancelled:
            subject = f"<s>{subject}</s>"
        lines.append(
            f"{item.starts_at:%H:%M}–{item.ends_at:%H:%M} · {emoji} {activity}"
        )
        lines.append(("❌ " if item.is_cancelled else "") + f"<b>{subject}</b>")
        if user.display_mode is not DisplayMode.compact:
            if user.show_location and (location := _location(item)):
                lines.append(f"📍 {escape(location)}")
            if user.display_mode is DisplayMode.detailed and user.show_teacher:
                if item.teacher_names:
                    lines.append("👤 " + escape("; ".join(item.teacher_names)))
            if user.show_delivery_mode:
                delivery_emoji, delivery = DELIVERY[item.delivery_mode]
                lines.append(f"{delivery_emoji} {delivery}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_lesson(lesson: ScheduleLesson) -> str:
    emoji, activity = ACTIVITY[lesson.activity_type]
    delivery_emoji, delivery = DELIVERY[lesson.delivery_mode]
    title = escape(lesson.subject)
    if lesson.is_cancelled:
        title = f"❌ <s>{title}</s>"
    lines = [
        f"{title}",
        "",
        f"{emoji} {activity}",
        f"🕐 {russian_date(lesson.starts_at.date())}, "
        f"{lesson.starts_at:%H:%M}–{lesson.ends_at:%H:%M}",
        f"{delivery_emoji} {delivery}",
    ]
    if lesson.teacher_names:
        lines.append("👤 " + escape("; ".join(lesson.teacher_names)))
    if location := _location(lesson):
        lines.append("📍 " + escape(location))
    if lesson.location_text and lesson.location_text != location:
        lines.append(escape(lesson.location_text))
    if lesson.is_cancelled:
        lines.extend(("", "Занятие оставлено в расписании как отменённое."))
    return "\n".join(lines)


def format_week(
    monday: date,
    group: GroupOption,
    lessons: tuple[ScheduleLesson, ...],
) -> str:
    sunday = monday.fromordinal(monday.toordinal() + 6)
    counts: dict[date, list[ScheduleLesson]] = defaultdict(list)
    for lesson in lessons:
        counts[lesson.starts_at.date()].append(lesson)
    lines = [
        f"🗓 <b>{monday.day} {MONTHS[monday.month - 1]} — "
        f"{sunday.day} {MONTHS[sunday.month - 1]}</b>",
        f"Группа {escape(group.display_name)}",
        "",
    ]
    for offset in range(7):
        day = monday.fromordinal(monday.toordinal() + offset)
        day_lessons = counts[day]
        active = sum(not item.is_cancelled for item in day_lessons)
        cancelled = sum(item.is_cancelled for item in day_lessons)
        summary = f"{active} зан." if active else "нет занятий"
        if cancelled:
            summary += f", ❌ {cancelled}"
        lines.append(
            f"<b>{WEEKDAYS[offset]}, {day.day} {MONTHS[day.month - 1]}</b> — {summary}"
        )
    return "\n".join(lines)


def format_full_week(
    monday: date,
    group: GroupOption,
    lessons: tuple[ScheduleLesson, ...],
) -> str:
    by_day: dict[date, list[ScheduleLesson]] = defaultdict(list)
    for lesson in lessons:
        by_day[lesson.starts_at.date()].append(lesson)
    lines = [f"🗓 <b>Расписание на неделю · {escape(group.display_name)}</b>", ""]
    for offset in range(7):
        day = monday.fromordinal(monday.toordinal() + offset)
        day_lessons = by_day[day]
        if not day_lessons:
            continue
        lines.append(f"<b>{russian_date(day)}</b>")
        for lesson in day_lessons:
            emoji, activity = ACTIVITY[lesson.activity_type]
            cancelled = "❌ " if lesson.is_cancelled else ""
            lines.append(
                f"{cancelled}{lesson.starts_at:%H:%M}–{lesson.ends_at:%H:%M} · "
                f"{emoji} {activity} · {escape(lesson.subject)}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def format_teacher_semester(
    educator: EducatorScheduleResponse,
    group: GroupOption,
    lessons: tuple[NormalizedLesson, ...],
) -> str:
    name = educator.full_name or educator.display_name
    lines = [
        f"👤 <b>{escape(name)}</b>",
        f"Занятия с группой {escape(group.display_name)} на семестр",
        "",
    ]
    if not lessons:
        lines.append("Совместных занятий в расписании не найдено.")
        return "\n".join(lines)
    for lesson in lessons:
        emoji, activity = ACTIVITY[lesson.activity_type]
        cancelled = "❌ " if lesson.is_cancelled else ""
        location = lesson.building_alias or lesson.location_text or "место не указано"
        if lesson.building_alias and lesson.room:
            location = f"{lesson.building_alias} · ауд. {lesson.room}"
        lines.append(
            f"{cancelled}<b>{lesson.starts_at:%d.%m, %H:%M–}"
            f"{lesson.ends_at:%H:%M}</b> · "
            f"{emoji} {activity}"
        )
        lines.append(f"{escape(lesson.subject)} · 📍 {escape(location)}")
        lines.append("")
    text = "\n".join(lines).rstrip()
    if len(text) > 4000:
        text = text[:3950] + "\n\n…Показана часть семестра."
    return text
