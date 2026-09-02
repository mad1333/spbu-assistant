from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select

from app.config import get_settings
from app.database.models import StudentGroup, TelegramUser
from app.database.session import async_session_factory
from app.mail.worker import poll_student_mail
from app.schedule.group_catalog import GroupCatalogClient, upsert_group_catalog
from app.schedule.spbu_client import SpbuTimetableClient, SpbuTimetableError
from app.schedule.sync_service import sync_group_week
from app.telegram.digests import send_due_digests
from app.telegram.notifications import notify_timetable_changes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW = ZoneInfo("Europe/Moscow")


def _week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


async def _group_ids() -> tuple[int, ...]:
    settings = get_settings()
    async with async_session_factory() as session:
        stored = tuple(
            await session.scalars(
                select(StudentGroup.source_id)
                .join(
                    TelegramUser,
                    TelegramUser.current_group_id == StudentGroup.id,
                )
                .where(StudentGroup.enabled.is_(True))
                .distinct()
            )
        )
    return tuple(dict.fromkeys((*settings.configured_group_ids, *stored)))


async def poll_once(
    client: SpbuTimetableClient | None = None,
    bot: Bot | None = None,
) -> None:
    today = datetime.now(MOSCOW).date()
    this_week_start, this_week_end = _week_bounds(today)
    ranges = (
        (this_week_start, this_week_end),
        (this_week_start + timedelta(days=7), this_week_end + timedelta(days=7)),
    )
    client = client or SpbuTimetableClient()

    for group_id in await _group_ids():
        for range_start, range_end in ranges:
            try:
                async with async_session_factory.begin() as session:
                    result = await sync_group_week(
                        session,
                        client,
                        group_id,
                        range_start,
                        range_end,
                    )
                logger.info(
                    "Synchronized group=%s range=%s..%s changed=%s events=%s",
                    group_id,
                    range_start,
                    range_end,
                    result.created_snapshot,
                    len(result.changes),
                )
                for change in result.changes:
                    logger.info("Timetable change: %s", change.message)
                await notify_timetable_changes(bot, result.group.id, result.changes)
            except SpbuTimetableError:
                logger.exception(
                    "SPbU timetable request failed for group=%s range=%s..%s",
                    group_id,
                    range_start,
                    range_end,
                )
            except Exception:
                logger.exception(
                    "Unexpected synchronization failure for group=%s range=%s..%s",
                    group_id,
                    range_start,
                    range_end,
                )
    await send_due_digests(bot)


async def refresh_group_catalog_once() -> int:
    catalog = await GroupCatalogClient().fetch()
    if not catalog:
        raise RuntimeError("Official AMCP group catalog returned no current groups")
    async with async_session_factory.begin() as session:
        count = await upsert_group_catalog(session, catalog)
    logger.info("Synchronized AMCP group catalog; groups=%s", count)
    return count


async def run() -> None:
    settings = get_settings()
    logger.info(
        "Worker started; timetable polling interval is %s seconds",
        settings.timetable_poll_interval_seconds,
    )
    bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None

    async def timetable_loop() -> None:
        while True:
            await poll_once(bot=bot)
            await asyncio.sleep(settings.timetable_poll_interval_seconds)

    async def mail_loop() -> None:
        while True:
            await poll_student_mail(bot)
            await asyncio.sleep(settings.mail_poll_interval_seconds)

    async def catalog_loop() -> None:
        while True:
            try:
                await refresh_group_catalog_once()
            except Exception:
                logger.exception("AMCP group catalog synchronization failed")
            await asyncio.sleep(settings.group_catalog_refresh_interval_seconds)

    try:
        await asyncio.gather(timetable_loop(), mail_loop(), catalog_loop())
    finally:
        if bot:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
