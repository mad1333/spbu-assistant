from __future__ import annotations

from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.telegram.handlers import router


def create_runtime() -> tuple[Bot, Dispatcher] | None:
    token = get_settings().telegram_bot_token
    if not token:
        return None
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return bot, dispatcher
