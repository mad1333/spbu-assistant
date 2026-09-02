from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import StudentGroup, StudentMailAccount, TelegramUser

MOSCOW = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True, slots=True)
class AdminOverview:
    users_total: int
    active_today: int
    active_week: int
    groups_selected: int
    mail_connected: int
    apple_calendar_requested: int
    google_calendar_requested: int


@dataclass(frozen=True, slots=True)
class AdminUser:
    telegram_id: int
    username: str | None
    display_name: str | None
    group_name: str | None
    last_active_at: datetime | None
    interaction_count: int
    mail_connected: bool


@dataclass(frozen=True, slots=True)
class GroupUsage:
    display_name: str
    users: int


async def admin_overview(session: AsyncSession) -> AdminOverview:
    now = datetime.now(UTC)

    async def count(where: object | None = None) -> int:
        query = select(func.count()).select_from(TelegramUser)
        if where is not None:
            query = query.where(where)
        return int(await session.scalar(query) or 0)

    return AdminOverview(
        users_total=await count(),
        active_today=await count(
            TelegramUser.last_active_at >= now - timedelta(hours=24)
        ),
        active_week=await count(TelegramUser.last_active_at >= now - timedelta(days=7)),
        groups_selected=await count(TelegramUser.current_group_id.is_not(None)),
        mail_connected=int(
            await session.scalar(
                select(func.count())
                .select_from(StudentMailAccount)
                .where(StudentMailAccount.enabled.is_(True))
            )
            or 0
        ),
        apple_calendar_requested=await count(
            TelegramUser.apple_calendar_requested_at.is_not(None)
        ),
        google_calendar_requested=await count(
            TelegramUser.google_calendar_requested_at.is_not(None)
        ),
    )


async def admin_users(
    session: AsyncSession,
    page: int,
    page_size: int = 8,
) -> tuple[tuple[AdminUser, ...], bool]:
    mail_exists = (
        select(StudentMailAccount.telegram_id)
        .where(
            StudentMailAccount.telegram_id == TelegramUser.telegram_id,
            StudentMailAccount.enabled.is_(True),
        )
        .exists()
    )
    rows = (
        await session.execute(
            select(
                TelegramUser.telegram_id,
                TelegramUser.username,
                TelegramUser.display_name,
                StudentGroup.display_name,
                TelegramUser.last_active_at,
                TelegramUser.interaction_count,
                mail_exists,
            )
            .outerjoin(StudentGroup, TelegramUser.current_group_id == StudentGroup.id)
            .order_by(
                TelegramUser.last_active_at.desc().nullslast(),
                TelegramUser.created_at.desc(),
            )
            .offset(page * page_size)
            .limit(page_size + 1)
        )
    ).all()
    has_next = len(rows) > page_size
    users = tuple(AdminUser(*row) for row in rows[:page_size])
    return users, has_next


async def admin_group_usage(session: AsyncSession) -> tuple[GroupUsage, ...]:
    rows = (
        await session.execute(
            select(StudentGroup.display_name, func.count(TelegramUser.telegram_id))
            .join(TelegramUser, TelegramUser.current_group_id == StudentGroup.id)
            .group_by(StudentGroup.id, StudentGroup.display_name)
            .order_by(func.count(TelegramUser.telegram_id).desc())
        )
    ).all()
    return tuple(GroupUsage(name, int(users)) for name, users in rows)


async def record_calendar_request(
    session: AsyncSession,
    telegram_id: int,
    service: str,
) -> None:
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        return
    now = datetime.now(UTC)
    if service == "apple":
        user.apple_calendar_requested_at = now
    elif service == "google":
        user.google_calendar_requested_at = now
    user.updated_at = now


def format_admin_overview(overview: AdminOverview) -> str:
    return (
        "🛡 <b>Админка</b>\n\n"
        f"Пользователей: <b>{overview.users_total}</b>\n"
        f"Активны за 24 часа: <b>{overview.active_today}</b>\n"
        f"Активны за 7 дней: <b>{overview.active_week}</b>\n"
        f"Выбрали группу: <b>{overview.groups_selected}</b>\n"
        f"Подключили почту: <b>{overview.mail_connected}</b>\n"
        "Запрашивали календарь:\n"
        f"• Apple — <b>{overview.apple_calendar_requested}</b>\n"
        f"• Google — <b>{overview.google_calendar_requested}</b>"
    )


def format_admin_users(users: tuple[AdminUser, ...], page: int) -> str:
    lines = [f"👥 <b>Пользователи · страница {page + 1}</b>"]
    if not users:
        lines.append("\nНа этой странице никого нет.")
        return "\n".join(lines)
    for user in users:
        name = escape(user.display_name or "Без имени")
        username = f" @{escape(user.username)}" if user.username else ""
        group = escape(user.group_name or "группа не выбрана")
        active = (
            user.last_active_at.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")
            if user.last_active_at
            else "до включения статистики"
        )
        mail = " · почта ✓" if user.mail_connected else ""
        lines.append(
            f"\n<b>{name}</b>{username}\n"
            f"ID: <code>{user.telegram_id}</code>\n"
            f"{group}{mail}\n"
            f"Активность: {active} · действий: {user.interaction_count}"
        )
    return "\n".join(lines)


def format_group_usage(groups: tuple[GroupUsage, ...]) -> str:
    lines = ["📊 <b>Пользователи по группам</b>"]
    if not groups:
        lines.append("\nПока никто не выбрал группу.")
        return "\n".join(lines)
    lines.extend(
        f"\n• {escape(group.display_name)} — <b>{group.users}</b>" for group in groups
    )
    return "".join(lines)
