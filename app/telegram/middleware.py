from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.database.models import TelegramUser
from app.database.session import async_session_factory


class UserActivityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if isinstance(user, User):
            await self._record(user)
        return await handler(event, data)

    async def _record(self, telegram_user: User) -> None:
        now = datetime.now(UTC)
        async with async_session_factory.begin() as session:
            user = await session.get(TelegramUser, telegram_user.id)
            if user is None:
                user = TelegramUser(
                    telegram_id=telegram_user.id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            user.username = telegram_user.username
            user.display_name = telegram_user.full_name
            user.last_active_at = now
            user.interaction_count = (user.interaction_count or 0) + 1
            user.updated_at = now
