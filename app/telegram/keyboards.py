from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import DisplayMode
from app.schedule.group_catalog import (
    LEVEL_ORDER,
    TOKEN_BY_LEVEL,
    direction_key,
    split_direction,
)
from app.schedule.teacher_directory import TeacherLink
from app.telegram.presentation import (
    MONTHS,
    english_subgroup_key,
    english_subgroup_label,
    lesson_button_text,
)
from app.telegram.types import GroupOption, ScheduleLesson, UserContext

SHORT_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def group_catalog_keyboard(groups: tuple[GroupOption, ...]) -> InlineKeyboardMarkup:
    grouped = {
        level: sum(split_direction(group.direction)[0] == level for group in groups)
        for level in LEVEL_ORDER
    }
    emoji = {"Бакалавриат": "🎓", "Магистратура": "📘", "Аспирантура": "🔬"}
    rows = [
        [
            InlineKeyboardButton(
                text=f"{emoji[level]} {level} · {grouped[level]} гр.",
                callback_data=f"group_level:{TOKEN_BY_LEVEL[level]}",
            )
        ]
        for level in LEVEL_ORDER
        if grouped[level]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_directions_keyboard(
    groups: tuple[GroupOption, ...],
    level: str,
) -> InlineKeyboardMarkup:
    directions: dict[str, tuple[str, int]] = {}
    for group in groups:
        group_level, label = split_direction(group.direction)
        if group_level != level or group.direction is None:
            continue
        current = directions.get(group.direction)
        directions[group.direction] = (label, 1 if current is None else current[1] + 1)
    rows = [
        [
            InlineKeyboardButton(
                text=f"{label[:54]} · {count} гр.",
                callback_data=f"group_direction:{direction_key(stored)}",
            )
        ]
        for stored, (label, count) in sorted(
            directions.items(),
            key=lambda item: item[1][0].casefold(),
        )
    ]
    rows.append(
        [InlineKeyboardButton(text="← Уровни обучения", callback_data="group_catalog")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def groups_keyboard(
    groups: tuple[GroupOption, ...],
    *,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=group.display_name,
            callback_data=f"group:{group.source_id}",
        )
        for group in groups
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    if back_callback:
        rows.append(
            [InlineKeyboardButton(text="← Направления", callback_data=back_callback)]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day_keyboard(
    target: date,
    lessons: tuple[ScheduleLesson, ...],
    *,
    today: date,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=lesson_button_text(lesson),
                callback_data=f"lesson:{lesson.lesson_id}",
            )
        ]
        for lesson in lessons
    ]
    navigation: list[InlineKeyboardButton] = []
    if target > today:
        navigation.append(
            InlineKeyboardButton(
                text="← День",
                callback_data=f"day:{target - timedelta(days=1):%Y-%m-%d}",
            )
        )
    navigation.append(
        InlineKeyboardButton(
            text="День →",
            callback_data=f"day:{target + timedelta(days=1):%Y-%m-%d}",
        )
    )
    rows.append(navigation)
    rows.extend(
        (
            [
                InlineKeyboardButton(
                    text="🗓 Выбрать день", callback_data=f"month:{target:%Y-%m}"
                ),
                InlineKeyboardButton(
                    text="Неделя", callback_data=f"week:{target:%Y-%m-%d}"
                ),
            ],
            [
                InlineKeyboardButton(text="⏭ Следующая пара", callback_data="next"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            ],
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_keyboard(lesson: ScheduleLesson) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Занятия преподавателя",
                    callback_data=f"teacher:{lesson.lesson_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="← К расписанию дня",
                    callback_data=f"day:{lesson.starts_at:%Y-%m-%d}",
                )
            ],
            [InlineKeyboardButton(text="🏠 Сегодня", callback_data="home")],
        ]
    )


def teacher_choices_keyboard(
    lesson: ScheduleLesson,
    teachers: tuple[TeacherLink, ...],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=teacher.display_name or f"Преподаватель {teacher.source_id}",
                callback_data=f"educator:{teacher.source_id}:{lesson.lesson_id}",
            )
        ]
        for teacher in teachers
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="← К занятию",
                callback_data=f"lesson:{lesson.lesson_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def teacher_schedule_keyboard(
    educator_id: int,
    lesson_id: uuid.UUID,
    official_url: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Официальная страница СПбГУ", url=official_url)],
            [
                InlineKeyboardButton(
                    text="← К занятию",
                    callback_data=f"lesson:{lesson_id}",
                )
            ],
            [InlineKeyboardButton(text="🏠 Сегодня", callback_data="home")],
        ]
    )


def week_keyboard(monday: date, *, today: date) -> InlineKeyboardMarkup:
    current_monday = today - timedelta(days=today.weekday())
    rows: list[list[InlineKeyboardButton]] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        if day < today:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{SHORT_WEEKDAYS[offset]} · {day.day} {MONTHS[day.month - 1]}"
                    ),
                    callback_data=f"day:{day:%Y-%m-%d}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if monday > current_monday:
        nav.append(
            InlineKeyboardButton(
                text="← Неделя",
                callback_data=f"week:{monday - timedelta(days=7):%Y-%m-%d}",
            )
        )
    nav.append(
        InlineKeyboardButton(
            text="Неделя →",
            callback_data=f"week:{monday + timedelta(days=7):%Y-%m-%d}",
        )
    )
    rows.extend(
        (
            nav,
            [
                InlineKeyboardButton(
                    text="📋 Всё расписание на неделю",
                    callback_data=f"weekall:{monday:%Y-%m-%d}",
                )
            ],
            [InlineKeyboardButton(text="🏠 Сегодня", callback_data="home")],
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def month_keyboard(year: int, month: int, *, today: date) -> InlineKeyboardMarkup:
    first = date(year, month, 1)
    previous_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    current_month = today.replace(day=1)
    header: list[InlineKeyboardButton] = []
    if first > current_month:
        header.append(
            InlineKeyboardButton(
                text="‹", callback_data=f"month:{previous_month:%Y-%m}"
            )
        )
    header.append(
        InlineKeyboardButton(text=f"{MONTHS[month - 1]} {year}", callback_data="noop")
    )
    header.append(
        InlineKeyboardButton(text="›", callback_data=f"month:{next_month:%Y-%m}")
    )
    rows = [header]
    rows.append(
        [
            InlineKeyboardButton(text=name, callback_data="noop")
            for name in SHORT_WEEKDAYS
        ]
    )
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            enabled = day.month == month and day >= today
            row.append(
                InlineKeyboardButton(
                    text=str(day.day) if day.month == month else "·",
                    callback_data=f"day:{day:%Y-%m-%d}" if enabled else "noop",
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🏠 Сегодня", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 Сменить группу", callback_data="change_group"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🇬🇧 Подгруппа английского",
                    callback_data="english_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎨 Вид главного экрана", callback_data="display_settings"
                )
            ],
            [InlineKeyboardButton(text="🔔 Рассылки", callback_data="digest_settings")],
            [
                InlineKeyboardButton(
                    text="📨 Студенческая почта", callback_data="mail_settings"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Календари", callback_data="calendar_settings"
                )
            ],
            [InlineKeyboardButton(text="🏠 Сегодня", callback_data="home")],
        ]
    )


def student_mail_keyboard(setup_url: str, *, connected: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="Переподключить почту" if connected else "Подключить почту",
                url=setup_url,
            )
        ]
    ]
    if connected:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✉️ Написать письмо", callback_data="mail_compose"
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отключить и удалить доступ",
                    callback_data="mail_disconnect_confirm",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Настройки", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mail_compose_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить", callback_data="mail_compose_cancel")]
        ]
    )


def mail_compose_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Отправить", callback_data="mail_compose_send"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить", callback_data="mail_compose_cancel"
                )
            ],
        ]
    )


def student_mail_disconnect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить подключение",
                    callback_data="mail_disconnect",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="mail_settings")],
        ]
    )


def apple_calendar_keyboard(setup_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть установку календарей", url=setup_url)],
            [
                InlineKeyboardButton(
                    text="Отключить все календари",
                    callback_data="calendar_revoke",
                )
            ],
            [
                InlineKeyboardButton(
                    text="← Календари", callback_data="calendar_settings"
                )
            ],
        ]
    )


def calendar_services_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=" Apple Calendar", callback_data="apple_calendar"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔵 Google Calendar", callback_data="google_calendar"
                )
            ],
            [InlineKeyboardButton(text="← Настройки", callback_data="settings")],
        ]
    )


def google_calendar_keyboard(setup_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить в Google Calendar", url=setup_url)],
            [
                InlineKeyboardButton(
                    text="Отключить все календари",
                    callback_data="calendar_revoke",
                )
            ],
            [
                InlineKeyboardButton(
                    text="← Календари", callback_data="calendar_settings"
                )
            ],
        ]
    )


def english_subgroups_keyboard(
    lessons: tuple[ScheduleLesson, ...],
    *,
    selected_key: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    seen: set[str] = set()
    for lesson in lessons:
        key = english_subgroup_key(lesson)
        if key in seen:
            continue
        seen.add(key)
        label = english_subgroup_label(lesson)
        if len(label) > 54:
            label = label[:53] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=("✓ " if key == selected_key else "") + label,
                    callback_data=f"english:{lesson.lesson_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← Настройки", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def display_settings_keyboard(user: UserContext) -> InlineKeyboardMarkup:
    def selected(mode: DisplayMode, label: str) -> str:
        return ("✓ " if user.display_mode is mode else "") + label

    def state(enabled: bool) -> str:
        return "вкл" if enabled else "выкл"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=selected(DisplayMode.compact, "Кратко"),
                    callback_data="mode:compact",
                ),
                InlineKeyboardButton(
                    text=selected(DisplayMode.normal, "Обычно"),
                    callback_data="mode:normal",
                ),
                InlineKeyboardButton(
                    text=selected(DisplayMode.detailed, "Подробно"),
                    callback_data="mode:detailed",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"Преподаватель: {state(user.show_teacher)}",
                    callback_data="toggle:teacher",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Аудитория: {state(user.show_location)}",
                    callback_data="toggle:location",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Формат: {state(user.show_delivery_mode)}",
                    callback_data="toggle:delivery",
                )
            ],
            [InlineKeyboardButton(text="← Настройки", callback_data="settings")],
        ]
    )


def digest_settings_keyboard(user: UserContext) -> InlineKeyboardMarkup:
    morning = "вкл" if user.morning_digest_enabled else "выкл"
    evening = "вкл" if user.evening_digest_enabled else "выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Утром {user.morning_digest_time:%H:%M}: {morning}",
                    callback_data="toggle:morning",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("✓ " if user.morning_digest_time.hour == hour else "")
                    + f"{hour:02d}:00",
                    callback_data=f"digesttime:morning:{hour:02d}:00",
                )
                for hour in (7, 8, 9)
            ],
            [
                InlineKeyboardButton(
                    text=f"Вечером {user.evening_digest_time:%H:%M}: {evening}",
                    callback_data="toggle:evening",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("✓ " if user.evening_digest_time.hour == hour else "")
                    + f"{hour:02d}:00",
                    callback_data=f"digesttime:evening:{hour:02d}:00",
                )
                for hour in (18, 20, 22)
            ],
            [InlineKeyboardButton(text="← Настройки", callback_data="settings")],
        ]
    )
