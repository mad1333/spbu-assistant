from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    DisplayMode,
    LessonRevision,
    ScheduleSnapshot,
    StudentGroup,
    TelegramUser,
)
from app.telegram.types import GroupOption, ScheduleLesson, UserContext

MOSCOW = ZoneInfo("Europe/Moscow")


def _group_option(group: StudentGroup) -> GroupOption:
    return GroupOption(group.id, group.source_id, group.display_name, group.direction)


def _lesson(revision: LessonRevision) -> ScheduleLesson:
    return ScheduleLesson(
        lesson_id=revision.lesson_id,
        starts_at=revision.starts_at.astimezone(MOSCOW),
        ends_at=revision.ends_at.astimezone(MOSCOW),
        subject=revision.subject,
        activity_type=revision.activity_type,
        delivery_mode=revision.delivery_mode,
        location_text=revision.location_text,
        building_alias=revision.building_alias,
        room=revision.room,
        teacher_names=tuple(revision.teacher_names),
        is_cancelled=revision.is_cancelled,
        observed_at=revision.observed_at,
    )


async def get_or_create_user(session: AsyncSession, telegram_id: int) -> UserContext:
    user = await session.scalar(
        select(TelegramUser)
        .where(TelegramUser.telegram_id == telegram_id)
        .options(selectinload(TelegramUser.current_group))
    )
    if user is None:
        now = datetime.now(UTC)
        user = TelegramUser(
            telegram_id=telegram_id,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.flush()

    return UserContext(
        telegram_id=user.telegram_id,
        current_group=_group_option(user.current_group) if user.current_group else None,
        display_mode=user.display_mode,
        show_teacher=user.show_teacher,
        show_location=user.show_location,
        show_delivery_mode=user.show_delivery_mode,
        morning_digest_enabled=user.morning_digest_enabled,
        morning_digest_time=user.morning_digest_time,
        evening_digest_enabled=user.evening_digest_enabled,
        evening_digest_time=user.evening_digest_time,
        english_subgroup_key=user.english_subgroup_key,
        english_subgroup_label=user.english_subgroup_label,
        calendar_generation=user.calendar_generation,
    )


async def get_existing_user(
    session: AsyncSession, telegram_id: int
) -> UserContext | None:
    user = await session.scalar(
        select(TelegramUser)
        .where(TelegramUser.telegram_id == telegram_id)
        .options(selectinload(TelegramUser.current_group))
    )
    if user is None:
        return None
    return UserContext(
        telegram_id=user.telegram_id,
        current_group=_group_option(user.current_group) if user.current_group else None,
        display_mode=user.display_mode,
        show_teacher=user.show_teacher,
        show_location=user.show_location,
        show_delivery_mode=user.show_delivery_mode,
        morning_digest_enabled=user.morning_digest_enabled,
        morning_digest_time=user.morning_digest_time,
        evening_digest_enabled=user.evening_digest_enabled,
        evening_digest_time=user.evening_digest_time,
        english_subgroup_key=user.english_subgroup_key,
        english_subgroup_label=user.english_subgroup_label,
        calendar_generation=user.calendar_generation,
    )


async def list_groups(session: AsyncSession) -> tuple[GroupOption, ...]:
    groups = tuple(
        await session.scalars(
            select(StudentGroup)
            .where(StudentGroup.enabled.is_(True))
            .order_by(StudentGroup.display_name)
        )
    )
    return tuple(_group_option(group) for group in groups)


async def set_user_group(
    session: AsyncSession,
    telegram_id: int,
    group_source_id: int,
) -> None:
    user = await session.get(TelegramUser, telegram_id)
    group = await session.scalar(
        select(StudentGroup).where(StudentGroup.source_id == group_source_id)
    )
    if user is None or group is None:
        raise LookupError("User or group was not found")
    user.current_group_id = group.id
    user.english_subgroup_key = None
    user.english_subgroup_label = None
    user.updated_at = datetime.now(UTC)


async def set_display_mode(
    session: AsyncSession,
    telegram_id: int,
    mode: DisplayMode,
) -> None:
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    user.display_mode = mode
    user.updated_at = datetime.now(UTC)


async def toggle_user_setting(
    session: AsyncSession,
    telegram_id: int,
    field: str,
) -> None:
    allowed = {
        "teacher": "show_teacher",
        "location": "show_location",
        "delivery": "show_delivery_mode",
        "morning": "morning_digest_enabled",
        "evening": "evening_digest_enabled",
    }
    attribute = allowed.get(field)
    if attribute is None:
        raise ValueError("Unknown user setting")
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    setattr(user, attribute, not getattr(user, attribute))
    user.updated_at = datetime.now(UTC)


async def set_digest_time(
    session: AsyncSession,
    telegram_id: int,
    kind: str,
    value: time,
) -> None:
    if kind not in {"morning", "evening"}:
        raise ValueError("Unknown digest kind")
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    setattr(user, f"{kind}_digest_time", value)
    user.updated_at = datetime.now(UTC)


async def set_english_subgroup(
    session: AsyncSession,
    telegram_id: int,
    key: str,
    label: str,
) -> None:
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    user.english_subgroup_key = key
    user.english_subgroup_label = label
    user.updated_at = datetime.now(UTC)


async def revoke_calendar_access(session: AsyncSession, telegram_id: int) -> int:
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    user.calendar_generation += 1
    user.updated_at = datetime.now(UTC)
    return user.calendar_generation


async def _latest_snapshot(
    session: AsyncSession,
    group_id: uuid.UUID,
    target: date,
) -> ScheduleSnapshot | None:
    return await session.scalar(
        select(ScheduleSnapshot)
        .where(
            ScheduleSnapshot.group_id == group_id,
            ScheduleSnapshot.range_start <= target,
            ScheduleSnapshot.range_end >= target,
        )
        .order_by(ScheduleSnapshot.fetched_at.desc())
        .limit(1)
    )


async def lessons_for_day(
    session: AsyncSession,
    group_id: uuid.UUID,
    target: date,
) -> tuple[ScheduleLesson, ...]:
    snapshot = await _latest_snapshot(session, group_id, target)
    if snapshot is None:
        return ()
    day_start = datetime.combine(target, time.min, MOSCOW)
    day_end = day_start + timedelta(days=1)
    revisions = tuple(
        await session.scalars(
            select(LessonRevision)
            .where(
                LessonRevision.snapshot_id == snapshot.id,
                LessonRevision.starts_at >= day_start,
                LessonRevision.starts_at < day_end,
            )
            .order_by(LessonRevision.starts_at, LessonRevision.subject)
        )
    )
    return tuple(_lesson(revision) for revision in revisions)


async def lessons_for_week(
    session: AsyncSession,
    group_id: uuid.UUID,
    monday: date,
) -> tuple[ScheduleLesson, ...]:
    snapshot = await _latest_snapshot(session, group_id, monday)
    if snapshot is None:
        return ()
    revisions = tuple(
        await session.scalars(
            select(LessonRevision)
            .where(LessonRevision.snapshot_id == snapshot.id)
            .order_by(LessonRevision.starts_at, LessonRevision.subject)
        )
    )
    return tuple(_lesson(revision) for revision in revisions)


async def latest_lesson(
    session: AsyncSession,
    lesson_id: uuid.UUID,
) -> ScheduleLesson | None:
    revision = await session.scalar(
        select(LessonRevision)
        .where(LessonRevision.lesson_id == lesson_id)
        .order_by(LessonRevision.observed_at.desc())
        .limit(1)
    )
    return _lesson(revision) if revision else None


async def calendar_lessons(
    session: AsyncSession,
    group_id: uuid.UUID,
    *,
    not_before: date,
    not_after: date,
) -> tuple[ScheduleLesson, ...]:
    starts = tuple(
        await session.scalars(
            select(ScheduleSnapshot.range_start)
            .where(
                ScheduleSnapshot.group_id == group_id,
                ScheduleSnapshot.range_end >= not_before,
                ScheduleSnapshot.range_start <= not_after,
            )
            .distinct()
            .order_by(ScheduleSnapshot.range_start)
        )
    )
    latest_by_id: dict[uuid.UUID, ScheduleLesson] = {}
    for monday in starts:
        for lesson in await lessons_for_week(session, group_id, monday):
            if not_before <= lesson.starts_at.date() <= not_after:
                previous = latest_by_id.get(lesson.lesson_id)
                if previous is None or lesson.observed_at > previous.observed_at:
                    latest_by_id[lesson.lesson_id] = lesson
    return tuple(
        sorted(
            latest_by_id.values(),
            key=lambda item: (item.starts_at, item.subject, item.lesson_id),
        )
    )
