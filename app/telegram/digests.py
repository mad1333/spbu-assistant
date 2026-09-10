from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from app.database.models import TelegramDayMessage, TelegramUser
from app.database.session import async_session_factory
from app.telegram.keyboards import day_keyboard
from app.telegram.presentation import apply_english_subgroup, format_day
from app.telegram.repository import get_existing_user, lessons_for_day

logger = logging.getLogger(__name__)


async def _send_digest(
    bot: Bot,
    telegram_id: int,
    target: date,
    kind: str,
    local_today: date,
) -> None:
    async with async_session_factory() as session:
        user = await get_existing_user(session, telegram_id)
        if user is None or user.current_group is None:
            return
        lessons = await lessons_for_day(session, user.current_group.id, target)
    lessons = apply_english_subgroup(
        lessons,
        user.english_subgroup_key,
        user.current_group.source_id,
    )
    text = format_day(target, user.current_group, lessons, user, today=local_today)
    message = await bot.send_message(
        telegram_id,
        text,
        reply_markup=day_keyboard(target, lessons, today=local_today),
        parse_mode=ParseMode.HTML,
    )
    now = datetime.now(UTC)
    async with async_session_factory.begin() as session:
        binding = await session.scalar(
            select(TelegramDayMessage).where(
                TelegramDayMessage.telegram_id == telegram_id,
                TelegramDayMessage.target_date == target,
                TelegramDayMessage.kind == kind,
            )
        )
        if binding is None:
            binding = TelegramDayMessage(
                id=uuid.uuid4(),
                telegram_id=telegram_id,
                target_date=target,
                kind=kind,
                message_id=message.message_id,
                created_at=now,
                updated_at=now,
            )
            session.add(binding)
        else:
            binding.message_id = message.message_id
            binding.updated_at = now
        stored_user = await session.get(TelegramUser, telegram_id)
        if stored_user is not None:
            if kind == "morning":
                stored_user.last_morning_digest_on = local_today
            else:
                stored_user.last_evening_digest_on = local_today


async def send_due_digests(bot: Bot | None) -> None:
    if bot is None:
        return
    async with async_session_factory() as session:
        users = tuple(
            await session.scalars(
                select(TelegramUser).where(TelegramUser.current_group_id.is_not(None))
            )
        )
    for user in users:
        try:
            timezone = ZoneInfo(user.timezone)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("Europe/Moscow")
        local_now = datetime.now(timezone)
        due: list[tuple[str, date]] = []
        if (
            user.morning_digest_enabled
            and local_now.time() >= user.morning_digest_time
            and user.last_morning_digest_on != local_now.date()
        ):
            due.append(("morning", local_now.date()))
        if (
            user.evening_digest_enabled
            and local_now.time() >= user.evening_digest_time
            and user.last_evening_digest_on != local_now.date()
        ):
            due.append(("evening", local_now.date() + timedelta(days=1)))
        for kind, target in due:
            try:
                await _send_digest(
                    bot,
                    user.telegram_id,
                    target,
                    kind,
                    local_now.date(),
                )
            except TelegramAPIError:
                logger.exception(
                    "Unable to send %s digest to Telegram user=%s",
                    kind,
                    user.telegram_id,
                )
