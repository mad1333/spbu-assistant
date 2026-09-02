from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.database.models import ScheduleSnapshot, StudentGroup
from app.database.session import async_session_factory
from app.schedule.spbu_client import SpbuTimetableClient
from app.schedule.sync_service import SyncResult, sync_group_week

_locks: defaultdict[tuple[int, date], asyncio.Lock] = defaultdict(asyncio.Lock)


def week_bounds(target: date) -> tuple[date, date]:
    monday = target - timedelta(days=target.weekday())
    return monday, monday + timedelta(days=6)


async def refresh_week_if_needed(
    group_source_id: int, target: date
) -> SyncResult | None:
    range_start, range_end = week_bounds(target)
    settings = get_settings()

    async with _locks[(group_source_id, range_start)]:
        async with async_session_factory() as session:
            group_id = await session.scalar(
                select(StudentGroup.id).where(StudentGroup.source_id == group_source_id)
            )
            if group_id is not None:
                last_checked = await session.scalar(
                    select(ScheduleSnapshot.fetched_at)
                    .where(
                        ScheduleSnapshot.group_id == group_id,
                        ScheduleSnapshot.range_start == range_start,
                        ScheduleSnapshot.range_end == range_end,
                    )
                    .order_by(ScheduleSnapshot.fetched_at.desc())
                    .limit(1)
                )
                if last_checked is not None:
                    age = datetime.now(UTC) - last_checked
                    if age < timedelta(seconds=settings.on_demand_freshness_seconds):
                        return None

        async with async_session_factory.begin() as session:
            return await sync_group_week(
                session,
                SpbuTimetableClient(),
                group_source_id,
                range_start,
                range_end,
            )
