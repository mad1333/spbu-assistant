from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.database.models import (
    ChangeKind,
    StudentGroup,
    TelegramDayMessage,
    TelegramUser,
)
from app.database.session import async_session_factory
from app.schedule.diff import LessonChange
from app.schedule.normalizer import normalize_text
from app.telegram.keyboards import day_keyboard
from app.telegram.presentation import (
    apply_english_subgroup,
    english_subgroup_choice_matches,
    format_day,
)
from app.telegram.repository import get_existing_user, lessons_for_day

logger = logging.getLogger(__name__)

CHANGE_EMOJI = {
    ChangeKind.added: "✨",
    ChangeKind.removed: "🗑",
    ChangeKind.cancelled: "❌",
    ChangeKind.restored: "✅",
    ChangeKind.time_changed: "🕐",
    ChangeKind.location_changed: "📍",
    ChangeKind.teacher_changed: "👤",
    ChangeKind.delivery_mode_changed: "🌐",
}


def _relevant_to_user(
    change: LessonChange,
    selected_english_key: str | None,
    group_source_id: int,
) -> bool:
    if selected_english_key is None:
        return True
    lesson = change.after or change.before
    if lesson is None:
        return True
    subject = normalize_text(lesson.subject)
    if "английский язык" not in subject or "траектория" not in subject:
        return True
    return english_subgroup_choice_matches(
        lesson.subject,
        lesson.teacher_names,
        lesson.starts_at.weekday(),
        selected_english_key,
        group_source_id,
    )


async def notify_timetable_changes(
    bot: Bot | None,
    group_id: uuid.UUID,
    changes: tuple[LessonChange, ...],
) -> None:
    if bot is None or not changes:
        return
    async with async_session_factory() as session:
        group_source_id = await session.scalar(
            select(StudentGroup.source_id).where(StudentGroup.id == group_id)
        )
        users = tuple(
            await session.scalars(
                select(TelegramUser).where(TelegramUser.current_group_id == group_id)
            )
        )
    for user in users:
        for change in changes:
            if group_source_id is None or not _relevant_to_user(
                change,
                user.english_subgroup_key,
                group_source_id,
            ):
                continue
            lesson = change.after or change.before
            if lesson is None:
                continue
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Посмотреть этот день",
                            callback_data=f"day:{lesson.starts_at:%Y-%m-%d}",
                        )
                    ],
                    [InlineKeyboardButton(text="🏠 Сегодня", callback_data="home")],
                ]
            )
            try:
                await bot.send_message(
                    user.telegram_id,
                    f"{CHANGE_EMOJI[change.kind]} <b>Изменение расписания</b>\n\n"
                    f"{escape(change.message)}",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramAPIError:
                logger.exception(
                    "Unable to notify Telegram user=%s about change=%s",
                    user.telegram_id,
                    change.kind.value,
                )
    affected_dates = {
        (change.after or change.before).starts_at.date()
        for change in changes
        if change.after or change.before
    }
    await refresh_bound_day_messages(bot, group_id, affected_dates)


async def refresh_bound_day_messages(
    bot: Bot,
    group_id: uuid.UUID,
    affected_dates: set[date],
) -> None:
    async with async_session_factory() as session:
        bindings = tuple(
            await session.scalars(
                select(TelegramDayMessage)
                .join(
                    TelegramUser,
                    TelegramUser.telegram_id == TelegramDayMessage.telegram_id,
                )
                .where(
                    TelegramUser.current_group_id == group_id,
                    TelegramDayMessage.target_date.in_(affected_dates),
                )
            )
        )
    for binding in bindings:
        async with async_session_factory() as session:
            user = await get_existing_user(session, binding.telegram_id)
            if user is None or user.current_group is None:
                continue
            lessons = await lessons_for_day(
                session, user.current_group.id, binding.target_date
            )
        lessons = apply_english_subgroup(
            lessons,
            user.english_subgroup_key,
            user.current_group.source_id,
        )
        local_today = datetime.now(ZoneInfo(user.timezone)).date()
        try:
            await bot.edit_message_text(
                format_day(
                    binding.target_date,
                    user.current_group,
                    lessons,
                    user,
                    today=local_today,
                ),
                chat_id=binding.telegram_id,
                message_id=binding.message_id,
                reply_markup=day_keyboard(
                    binding.target_date, lessons, today=local_today
                ),
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).casefold():
                logger.exception(
                    "Unable to refresh Telegram day message user=%s date=%s",
                    binding.telegram_id,
                    binding.target_date,
                )
