from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date, datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.calendar.tokens import issue_calendar_token
from app.config import get_settings
from app.database.models import DisplayMode, TelegramUser
from app.database.session import async_session_factory
from app.mail.client import (
    StudentMailAuthenticationError,
    StudentMailError,
)
from app.mail.client import (
    send_message as send_student_mail,
)
from app.mail.crypto import decrypt_app_password
from app.mail.repository import (
    disconnect_mail_account,
    mail_account_config,
    mail_account_status,
)
from app.mail.tokens import issue_mail_setup_token
from app.schedule.group_catalog import (
    LEVEL_TOKENS,
    TOKEN_BY_LEVEL,
    direction_key,
    split_direction,
)
from app.schedule.normalizer import normalize_event, normalize_text
from app.schedule.on_demand import refresh_week_if_needed, week_bounds
from app.schedule.spbu_client import SpbuTimetableClient, SpbuTimetableError
from app.schedule.teacher_directory import TeacherDirectoryClient
from app.telegram.keyboards import (
    apple_calendar_keyboard,
    calendar_services_keyboard,
    day_keyboard,
    digest_settings_keyboard,
    display_settings_keyboard,
    english_subgroups_keyboard,
    google_calendar_keyboard,
    group_catalog_keyboard,
    group_directions_keyboard,
    groups_keyboard,
    lesson_keyboard,
    mail_compose_cancel_keyboard,
    mail_compose_confirm_keyboard,
    month_keyboard,
    settings_keyboard,
    student_mail_disconnect_keyboard,
    student_mail_keyboard,
    teacher_choices_keyboard,
    teacher_schedule_keyboard,
    week_keyboard,
)
from app.telegram.presentation import (
    apply_english_subgroup,
    english_subgroup_key,
    english_subgroup_label,
    format_day,
    format_full_week,
    format_lesson,
    format_teacher_semester,
    format_week,
    is_english_subgroup,
)
from app.telegram.repository import (
    get_or_create_user,
    latest_lesson,
    lessons_for_day,
    lessons_for_week,
    list_groups,
    revoke_calendar_access,
    set_digest_time,
    set_display_mode,
    set_english_subgroup,
    set_user_group,
    toggle_user_setting,
)
from app.telegram.types import UserContext

router = Router(name="timetable")
MOSCOW = ZoneInfo("Europe/Moscow")
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


class MailCompose(StatesGroup):
    recipient = State()
    subject = State()
    body = State()
    confirmation = State()


async def _context(telegram_id: int) -> UserContext:
    async with async_session_factory.begin() as session:
        return await get_or_create_user(session, telegram_id)


async def _show_groups(message: Message, *, edit: bool) -> None:
    async with async_session_factory() as session:
        groups = await list_groups(session)
    if any(group.direction for group in groups):
        text = (
            "👋 <b>Выберите уровень обучения</b>\n\n"
            "Затем выберите направление и свою группу ПМ‑ПУ. "
            "Позже её можно сменить в настройках."
        )
        markup = group_catalog_keyboard(groups)
    else:
        text = (
            "👋 <b>Выберите учебную группу</b>\n\nПозже её можно сменить в настройках."
        )
        markup = groups_keyboard(groups)
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)


async def _refresh(group_source_id: int, target: date) -> bool:
    try:
        await refresh_week_if_needed(group_source_id, target)
        return True
    except SpbuTimetableError:
        return False


async def _show_day(
    message: Message, telegram_id: int, target: date, *, edit: bool
) -> None:
    user = await _context(telegram_id)
    if user.current_group is None:
        await _show_groups(message, edit=edit)
        return
    await _refresh(user.current_group.source_id, target)
    async with async_session_factory() as session:
        lessons = await lessons_for_day(session, user.current_group.id, target)
    lessons = apply_english_subgroup(lessons, user.english_subgroup_key)
    today = datetime.now(MOSCOW).date()
    text = format_day(target, user.current_group, lessons, user, today=today)
    markup = day_keyboard(target, lessons, today=today)
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@router.message(CommandStart())
async def start(message: Message) -> None:
    if message.from_user is None:
        return
    user = await _context(message.from_user.id)
    if user.current_group is None:
        await _show_groups(message, edit=False)
    else:
        await _show_day(
            message,
            message.from_user.id,
            datetime.now(MOSCOW).date(),
            edit=False,
        )


@router.callback_query(F.data.startswith("group:"))
async def choose_group(callback: CallbackQuery) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message):
        return
    await callback.answer("Группа сохранена")
    group_source_id = int(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    async with async_session_factory.begin() as session:
        await get_or_create_user(session, callback.from_user.id)
        await set_user_group(session, callback.from_user.id, group_source_id)
    await _show_day(
        callback.message,
        callback.from_user.id,
        datetime.now(MOSCOW).date(),
        edit=True,
    )


@router.callback_query(F.data == "group_catalog")
async def show_group_catalog(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await _show_groups(callback.message, edit=True)


@router.callback_query(F.data.startswith("group_level:"))
async def show_group_directions(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    token = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    level = LEVEL_TOKENS.get(token)
    if level is None:
        await callback.answer("Уровень обучения не найден", show_alert=True)
        return
    async with async_session_factory() as session:
        groups = await list_groups(session)
    await callback.answer()
    await callback.message.edit_text(
        f"🎓 <b>{escape(level)}</b>\n\nВыберите направление:",
        reply_markup=group_directions_keyboard(groups, level),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("group_direction:"))
async def show_direction_groups(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    key = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    async with async_session_factory() as session:
        groups = await list_groups(session)
    selected = tuple(
        group
        for group in groups
        if group.direction is not None and direction_key(group.direction) == key
    )
    if not selected:
        await callback.answer(
            "Направление обновилось — выберите его ещё раз", show_alert=True
        )
        await _show_groups(callback.message, edit=True)
        return
    level, direction = split_direction(selected[0].direction)
    await callback.answer()
    await callback.message.edit_text(
        f"📚 <b>{escape(direction)}</b>\n\nВыберите учебную группу:",
        reply_markup=groups_keyboard(
            selected,
            back_callback=f"group_level:{TOKEN_BY_LEVEL.get(level, 'bachelor')}",
        ),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer("Проверяю расписание…")
    await _show_day(
        callback.message,
        callback.from_user.id,
        datetime.now(MOSCOW).date(),
        edit=True,
    )


@router.callback_query(F.data.startswith("day:"))
async def show_day(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    target = date.fromisoformat(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    if target < datetime.now(MOSCOW).date():
        await callback.answer("Прошедшие дни недоступны", show_alert=False)
        return
    await callback.answer("Проверяю расписание…")
    await _show_day(callback.message, callback.from_user.id, target, edit=True)


@router.callback_query(F.data.startswith("lesson:"))
async def show_lesson(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    lesson_id = uuid.UUID(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    async with async_session_factory() as session:
        lesson = await latest_lesson(session, lesson_id)
    if lesson is None:
        await callback.answer("Занятие больше не найдено", show_alert=True)
        return
    await callback.message.edit_text(
        format_lesson(lesson),
        reply_markup=lesson_keyboard(lesson),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("week:"))
async def show_week(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    target = date.fromisoformat(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    monday, _ = week_bounds(target)
    today = datetime.now(MOSCOW).date()
    if monday < week_bounds(today)[0]:
        await callback.answer("Прошедшие недели недоступны")
        return
    await callback.answer("Обновляю неделю…")
    user = await _context(callback.from_user.id)
    if user.current_group is None:
        await _show_groups(callback.message, edit=True)
        return
    await _refresh(user.current_group.source_id, monday)
    async with async_session_factory() as session:
        lessons = await lessons_for_week(session, user.current_group.id, monday)
    lessons = apply_english_subgroup(lessons, user.english_subgroup_key)
    await callback.message.edit_text(
        format_week(monday, user.current_group, lessons),
        reply_markup=week_keyboard(monday, today=today),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("weekall:"))
async def show_full_week(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    monday = date.fromisoformat(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    await callback.answer("Обновляю неделю…")
    user = await _context(callback.from_user.id)
    if user.current_group is None:
        await _show_groups(callback.message, edit=True)
        return
    await _refresh(user.current_group.source_id, monday)
    async with async_session_factory() as session:
        lessons = await lessons_for_week(session, user.current_group.id, monday)
    lessons = apply_english_subgroup(lessons, user.english_subgroup_key)
    await callback.message.edit_text(
        format_full_week(monday, user.current_group, lessons),
        reply_markup=week_keyboard(monday, today=datetime.now(MOSCOW).date()),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("month:"))
async def show_month(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    year, month = map(int, callback.data.split(":", 1)[1].split("-"))  # type: ignore[union-attr]
    await callback.message.edit_text(
        "🗓 <b>Выберите день</b>",
        reply_markup=month_keyboard(year, month, today=datetime.now(MOSCOW).date()),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "next")
async def show_next_lesson(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer("Ищу следующую пару…")
    user = await _context(callback.from_user.id)
    if user.current_group is None:
        await _show_groups(callback.message, edit=True)
        return
    now = datetime.now(MOSCOW)
    monday, _ = week_bounds(now.date())
    await _refresh(user.current_group.source_id, now.date())
    async with async_session_factory() as session:
        lessons = list(await lessons_for_week(session, user.current_group.id, monday))
        if not any(item.starts_at > now and not item.is_cancelled for item in lessons):
            next_monday = monday + timedelta(days=7)
            await _refresh(user.current_group.source_id, next_monday)
            lessons.extend(
                await lessons_for_week(session, user.current_group.id, next_monday)
            )
    lessons = list(apply_english_subgroup(tuple(lessons), user.english_subgroup_key))
    upcoming = [
        item for item in lessons if item.starts_at > now and not item.is_cancelled
    ]
    if not upcoming:
        await callback.message.edit_text(
            "Ближайших занятий в просмотренных неделях нет ✨",
            reply_markup=day_keyboard(now.date(), (), today=now.date()),
        )
        return
    lesson = min(upcoming, key=lambda item: item.starts_at)
    remaining = lesson.starts_at - now
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes = remainder // 60
    text = format_lesson(lesson) + f"\n\n⏳ До начала: <b>{hours} ч {minutes} мин</b>"
    await callback.message.edit_text(
        text,
        reply_markup=lesson_keyboard(lesson),
        parse_mode=ParseMode.HTML,
    )


def _semester_bounds(reference: date) -> tuple[date, date]:
    if reference.month >= 8:
        return date(reference.year, 8, 1), date(reference.year + 1, 1, 31)
    return date(reference.year, 2, 1), date(reference.year, 7, 31)


async def _show_teacher_semester(
    message: Message,
    telegram_id: int,
    educator_id: int,
    lesson_id: uuid.UUID,
) -> None:
    user = await _context(telegram_id)
    if user.current_group is None:
        await _show_groups(message, edit=True)
        return
    lesson = None
    async with async_session_factory() as session:
        lesson = await latest_lesson(session, lesson_id)
    reference = lesson.starts_at.date() if lesson else datetime.now(MOSCOW).date()
    date_from, date_to = _semester_bounds(reference)
    educator = await SpbuTimetableClient().fetch_educator_schedule(
        educator_id,
        date_from,
        date_to,
    )
    group_name = normalize_text(user.current_group.display_name.removeprefix("Группа "))
    matched = []
    for day in educator.days:
        for event in day.events:
            groups = {
                normalize_text(value)
                for value in event.contingent_unit_name.split(",")
                if value.strip()
            }
            if group_name in groups:
                matched.append(normalize_event(user.current_group.source_id, event))
    official_url = (
        str(get_settings().spbu_base_url).rstrip("/") + f"/EducatorEvents/{educator_id}"
    )
    await message.edit_text(
        format_teacher_semester(
            educator,
            user.current_group,
            tuple(sorted(matched, key=lambda item: item.starts_at)),
        ),
        reply_markup=teacher_schedule_keyboard(educator_id, lesson_id, official_url),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("teacher:"))
async def show_teacher_choices(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer("Загружаю преподавателей…")
    lesson_id = uuid.UUID(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    user = await _context(callback.from_user.id)
    if user.current_group is None:
        await _show_groups(callback.message, edit=True)
        return
    async with async_session_factory() as session:
        lesson = await latest_lesson(session, lesson_id)
    if lesson is None:
        await callback.answer("Занятие больше не найдено", show_alert=True)
        return
    try:
        teachers = await TeacherDirectoryClient().teachers_for_lesson(
            user.current_group.source_id,
            lesson.starts_at,
            lesson.subject,
            lesson.location_text,
        )
    except SpbuTimetableError:
        await callback.answer(
            "Не удалось загрузить страницу преподавателя", show_alert=True
        )
        return
    if not teachers:
        await callback.answer("Преподаватель не указан на сайте", show_alert=True)
        return
    if len(teachers) == 1:
        await _show_teacher_semester(
            callback.message,
            callback.from_user.id,
            teachers[0].source_id,
            lesson_id,
        )
        return
    await callback.message.edit_text(
        "👤 <b>Выберите преподавателя</b>",
        reply_markup=teacher_choices_keyboard(lesson, teachers),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("educator:"))
async def show_selected_teacher(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer("Загружаю расписание на семестр…")
    _, educator_id_text, lesson_id_text = callback.data.split(":", 2)  # type: ignore[union-attr]
    await _show_teacher_semester(
        callback.message,
        callback.from_user.id,
        int(educator_id_text),
        uuid.UUID(lesson_id_text),
    )


@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>Настройки</b>\n\nЗдесь меняются группа, вид главного экрана и рассылки.",
        reply_markup=settings_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "mail_settings")
async def show_mail_settings(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    settings = get_settings()
    if not settings.token_signing_key or not settings.mail_credentials_key:
        await callback.answer("Почта ещё не настроена на сервере", show_alert=True)
        return
    async with async_session_factory() as session:
        user = await session.get(TelegramUser, callback.from_user.id)
        status_info = await mail_account_status(session, callback.from_user.id)
    if user is None:
        await callback.answer("Сначала выберите группу", show_alert=True)
        return
    token = issue_mail_setup_token(
        user.telegram_id,
        user.mail_setup_generation,
        settings.token_signing_key,
    )
    setup_url = f"{settings.public_base_url.rstrip('/')}/mail/setup/{token}"
    if status_info.connected:
        checked = (
            status_info.last_checked_at.astimezone(MOSCOW).strftime("%d.%m %H:%M")
            if status_info.last_checked_at
            else "ещё не проверялась"
        )
        state = (
            f"Подключена: <b>{escape(status_info.address or '')}</b>\n"
            f"Последняя проверка: {checked}"
        )
        if status_info.last_error:
            state += "\n⚠️ Последняя проверка завершилась ошибкой"
    else:
        state = "Почта пока не подключена."
    await callback.answer()
    await callback.message.edit_text(
        "📨 <b>Студенческая почта</b>\n\n"
        f"{state}\n\n"
        "После подключения бот будет присылать отправителя, тему, время и читаемый "
        "текст каждого нового письма. Здесь же можно отправлять письма от имени "
        "студенческой почты. Уже лежащие во входящих письма отправлены не будут.\n\n"
        "Данные вводятся на защищённой странице VPS, а не в Telegram.",
        reply_markup=student_mail_keyboard(setup_url, connected=status_info.connected),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "mail_compose")
async def begin_mail_compose(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        return
    async with async_session_factory() as session:
        account = await mail_account_config(session, callback.from_user.id)
    if account is None:
        await callback.answer("Сначала подключите студенческую почту", show_alert=True)
        return
    await state.clear()
    await state.set_state(MailCompose.recipient)
    await callback.answer()
    await callback.message.edit_text(
        "✉️ <b>Новое письмо</b>\n\n"
        "Шаг 1 из 3. Отправьте адрес получателя одним сообщением.\n"
        "Например: <code>teacher@spbu.ru</code>",
        reply_markup=mail_compose_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(MailCompose.recipient)
async def mail_compose_recipient(message: Message, state: FSMContext) -> None:
    recipient = (message.text or "").strip()
    if len(recipient) > 320 or not EMAIL_PATTERN.fullmatch(recipient):
        await message.answer(
            "Не похоже на адрес почты. Отправьте один адрес вида "
            "<code>name@example.ru</code>.",
            reply_markup=mail_compose_cancel_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return
    await state.update_data(recipient=recipient)
    await state.set_state(MailCompose.subject)
    await message.answer(
        "Шаг 2 из 3. Теперь отправьте тему письма.\n"
        "Если тема не нужна, отправьте один знак <code>—</code>.",
        reply_markup=mail_compose_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(MailCompose.subject)
async def mail_compose_subject(message: Message, state: FSMContext) -> None:
    subject = (message.text or "").strip()
    if subject in {"-", "—"}:
        subject = "Без темы"
    if not subject or len(subject) > 300 or "\n" in subject or "\r" in subject:
        await message.answer(
            "Тема должна быть одной строкой длиной до 300 символов.",
            reply_markup=mail_compose_cancel_keyboard(),
        )
        return
    await state.update_data(subject=subject)
    await state.set_state(MailCompose.body)
    await message.answer(
        "Шаг 3 из 3. Отправьте текст письма одним сообщением.\n\n"
        "Можно использовать переносы строк и обычное форматирование Telegram.",
        reply_markup=mail_compose_cancel_keyboard(),
    )


@router.message(MailCompose.body)
async def mail_compose_body(message: Message, state: FSMContext) -> None:
    body_text = (message.text or "").strip()
    if not body_text:
        await message.answer(
            "Пока поддерживается текстовое письмо без вложений. "
            "Отправьте текст сообщением.",
            reply_markup=mail_compose_cancel_keyboard(),
        )
        return
    if len(body_text) > 12_000:
        await message.answer(
            "Письмо слишком длинное: максимум 12 000 символов.",
            reply_markup=mail_compose_cancel_keyboard(),
        )
        return
    data = await state.get_data()
    body_html = message.html_text.replace("\n", "<br>")
    await state.update_data(body_text=body_text, body_html=body_html)
    await state.set_state(MailCompose.confirmation)
    preview = body_text if len(body_text) <= 700 else body_text[:700] + "…"
    await message.answer(
        "<b>Проверьте письмо</b>\n\n"
        f"<b>Кому:</b> {escape(str(data['recipient']))}\n"
        f"<b>Тема:</b> {escape(str(data['subject']))}\n\n"
        f"{escape(preview)}",
        reply_markup=mail_compose_confirm_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "mail_compose_send", MailCompose.confirmation)
async def confirm_mail_send(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer("Отправляю…")
    data = await state.get_data()
    async with async_session_factory() as session:
        account = await mail_account_config(session, callback.from_user.id)
    settings = get_settings()
    if account is None or not settings.mail_credentials_key:
        await state.clear()
        await callback.message.edit_text(
            "Почтовое подключение больше недоступно. Подключите почту заново.",
            reply_markup=settings_keyboard(),
        )
        return
    try:
        password = decrypt_app_password(
            account.encrypted_app_password,
            callback.from_user.id,
            settings.mail_credentials_key,
        )
        await asyncio.to_thread(
            send_student_mail,
            settings.mail_smtp_host,
            settings.mail_smtp_port,
            account.address,
            password,
            str(data["recipient"]),
            str(data["subject"]),
            str(data["body_text"]),
            str(data["body_html"]),
        )
        password = ""
    except StudentMailAuthenticationError:
        await callback.message.edit_text(
            "⚠️ Почтовый сервер не принял пароль. Переподключите студенческую почту.",
            reply_markup=settings_keyboard(),
        )
        await state.clear()
        return
    except (StudentMailError, ValueError):
        await callback.message.edit_text(
            "Не удалось отправить письмо: почтовый сервер временно недоступен. "
            "Черновик пока сохранён — нажмите «Отправить» ещё раз позже.",
            reply_markup=mail_compose_confirm_keyboard(),
        )
        return
    await state.clear()
    await callback.message.edit_text(
        "✅ <b>Письмо отправлено</b>\n\n"
        f"Получатель: {escape(str(data['recipient']))}\n"
        f"Тема: {escape(str(data['subject']))}",
        reply_markup=settings_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "mail_compose_cancel")
async def cancel_mail_compose(callback: CallbackQuery, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        return
    await state.clear()
    await callback.answer("Письмо отменено")
    await callback.message.edit_text(
        "Отправка письма отменена.",
        reply_markup=settings_keyboard(),
    )


@router.callback_query(F.data == "mail_compose_send")
async def expired_mail_compose(callback: CallbackQuery) -> None:
    await callback.answer(
        "Черновик уже отправлен или устарел. Создайте новое письмо.",
        show_alert=True,
    )


@router.callback_query(F.data == "mail_disconnect_confirm")
async def confirm_mail_disconnect(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await callback.message.edit_text(
        "⚠️ <b>Отключить студенческую почту?</b>\n\n"
        "Зашифрованный пароль и история служебных уведомлений будут удалены с сервера. "
        "Письма в самом почтовом ящике не изменятся.",
        reply_markup=student_mail_disconnect_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "mail_disconnect")
async def disconnect_student_mail(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    async with async_session_factory.begin() as session:
        await disconnect_mail_account(session, callback.from_user.id)
    await callback.answer("Почта отключена")
    await callback.message.edit_text(
        "📨 <b>Студенческая почта отключена</b>\n\n"
        "Сохранённый доступ удалён. Если использовался отдельный пароль приложения, "
        "его также можно отозвать в настройках VK WorkSpace.",
        reply_markup=settings_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "calendar_settings")
async def show_calendar_settings(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await callback.message.edit_text(
        "📅 <b>Календари</b>\n\n"
        "Выберите приложение. В обоих случаях календарь подписывается на живое "
        "расписание и получает опубликованные изменения автоматически.",
        reply_markup=calendar_services_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "apple_calendar")
async def show_apple_calendar(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    settings = get_settings()
    if not settings.token_signing_key:
        await callback.answer("Календарь ещё не настроен на сервере", show_alert=True)
        return
    user = await _context(callback.from_user.id)
    token = issue_calendar_token(
        user.telegram_id,
        user.calendar_generation,
        settings.token_signing_key,
    )
    setup_url = f"{settings.public_base_url.rstrip('/')}/calendar/setup/{token}"
    await callback.answer()
    await callback.message.edit_text(
        " <b>Apple Calendar</b>\n\n"
        "Откройте установку и добавьте нужные типы занятий. Обновления приходят "
        "через подписку; частоту фактической проверки выбирает Apple.\n\n"
        "Для разных цветов занятия разделены на несколько календарей.",
        reply_markup=apple_calendar_keyboard(setup_url),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "google_calendar")
async def show_google_calendar(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    settings = get_settings()
    if not settings.token_signing_key:
        await callback.answer("Календарь ещё не настроен на сервере", show_alert=True)
        return
    user = await _context(callback.from_user.id)
    token = issue_calendar_token(
        user.telegram_id,
        user.calendar_generation,
        settings.token_signing_key,
    )
    setup_url = f"{settings.public_base_url.rstrip('/')}/calendar/google/setup/{token}"
    await callback.answer()
    await callback.message.edit_text(
        "🔵 <b>Google Calendar</b>\n\n"
        "Откройте установку и добавьте нужные типы занятий. Для разных цветов они "
        "создаются отдельными календарями.\n\n"
        "Бот публикует изменения сразу после проверки расписания, но момент их "
        "появления определяет Google.",
        reply_markup=google_calendar_keyboard(setup_url),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "calendar_revoke")
async def revoke_calendar(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    async with async_session_factory.begin() as session:
        await revoke_calendar_access(session, callback.from_user.id)
    await callback.answer("Доступ календарей отключён")
    await callback.message.edit_text(
        "📅 <b>Доступ календарей отключён</b>\n\n"
        "Старые ссылки Apple и Google больше не обновляются.\n\n"
        "Чтобы убрать календарь с iPhone: Календарь → Календари → ⓘ → "
        "Удалить календарь.\n"
        "На Mac: правая кнопка по календарю → Отписаться.\n"
        "В Google Calendar: Настройки календаря → Удалить календарь → "
        "Отказаться от подписки.",
        reply_markup=settings_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "change_group")
async def change_group(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    await _show_groups(callback.message, edit=True)


@router.callback_query(F.data == "english_settings")
async def show_english_settings(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer("Ищу доступные подгруппы…")
    user = await _context(callback.from_user.id)
    if user.current_group is None:
        await _show_groups(callback.message, edit=True)
        return
    today = datetime.now(MOSCOW).date()
    monday, _ = week_bounds(today)
    candidates = []
    for offset in range(4):
        week = monday + timedelta(days=offset * 7)
        await _refresh(user.current_group.source_id, week)
        async with async_session_factory() as session:
            candidates.extend(
                await lessons_for_week(session, user.current_group.id, week)
            )
    english_lessons = tuple(item for item in candidates if is_english_subgroup(item))
    if not english_lessons:
        await callback.message.edit_text(
            "🇬🇧 Подгруппы английского пока не появились в расписании.",
            reply_markup=settings_keyboard(),
        )
        return
    selected = escape(user.english_subgroup_label or "не выбрана")
    await callback.message.edit_text(
        f"🇬🇧 <b>Подгруппа английского</b>\n\n"
        f"Сейчас: {selected}\nВыберите свой вариант:",
        reply_markup=english_subgroups_keyboard(
            english_lessons,
            selected_key=user.english_subgroup_key,
        ),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("english:"))
async def choose_english_subgroup(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    lesson_id = uuid.UUID(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    async with async_session_factory() as session:
        lesson = await latest_lesson(session, lesson_id)
    if lesson is None:
        await callback.answer("Вариант больше не найден", show_alert=True)
        return
    key = english_subgroup_key(lesson)
    label = english_subgroup_label(lesson)
    async with async_session_factory.begin() as session:
        await set_english_subgroup(session, callback.from_user.id, key, label)
    await callback.answer("Подгруппа сохранена")
    await callback.message.edit_text(
        f"🇬🇧 <b>Подгруппа сохранена</b>\n\n{escape(label)}",
        reply_markup=settings_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "display_settings")
async def show_display_settings(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    user = await _context(callback.from_user.id)
    await callback.message.edit_text(
        "🎨 <b>Вид главного экрана</b>\n\nВыберите плотность и нужные поля.",
        reply_markup=display_settings_keyboard(user),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("mode:"))
async def change_display_mode(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    mode = DisplayMode(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    async with async_session_factory.begin() as session:
        await set_display_mode(session, callback.from_user.id, mode)
    await callback.answer("Вид сохранён")
    user = await _context(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=display_settings_keyboard(user)
    )


@router.callback_query(F.data == "digest_settings")
async def show_digest_settings(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    await callback.answer()
    user = await _context(callback.from_user.id)
    await callback.message.edit_text(
        "🔔 <b>Рассылки</b>\n\nУтром — расписание на сегодня, вечером — на завтра.",
        reply_markup=digest_settings_keyboard(user),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("toggle:"))
async def toggle_setting(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    field = callback.data.split(":", 1)[1]  # type: ignore[union-attr]
    async with async_session_factory.begin() as session:
        await toggle_user_setting(session, callback.from_user.id, field)
    await callback.answer("Настройка сохранена")
    user = await _context(callback.from_user.id)
    markup = (
        digest_settings_keyboard(user)
        if field in {"morning", "evening"}
        else display_settings_keyboard(user)
    )
    await callback.message.edit_reply_markup(reply_markup=markup)


@router.callback_query(F.data.startswith("digesttime:"))
async def change_digest_time(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        return
    _, kind, value = callback.data.split(":", 2)  # type: ignore[union-attr]
    hour, minute = map(int, value.split(":"))
    async with async_session_factory.begin() as session:
        await set_digest_time(
            session,
            callback.from_user.id,
            kind,
            time(hour, minute),
        )
    await callback.answer("Время сохранено")
    user = await _context(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=digest_settings_keyboard(user)
    )


@router.callback_query(F.data == "noop")
async def pending_action(callback: CallbackQuery) -> None:
    await callback.answer("Этот раздел подключим на следующем шаге")
