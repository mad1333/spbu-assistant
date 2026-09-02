from __future__ import annotations

import asyncio
import logging
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import get_settings
from app.database.session import async_session_factory
from app.mail.client import (
    MailboxCursor,
    StudentMailAuthenticationError,
    StudentMailError,
    fetch_new_messages,
)
from app.mail.crypto import decrypt_app_password
from app.mail.repository import (
    MailAccountConfig,
    enabled_mail_accounts,
    mark_mail_error_notified,
    mark_mail_notified,
    pending_mail_notifications,
    record_mail_failure,
    record_mail_poll,
    should_notify_mail_error,
)

logger = logging.getLogger(__name__)
MOSCOW = ZoneInfo("Europe/Moscow")
MAIL_URL = "https://biz.mail.ru/"
TELEGRAM_TEXT_LIMIT = 3900


def _mail_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Написать письмо", callback_data="mail_compose"
                )
            ],
            [InlineKeyboardButton(text="Открыть почту", url=MAIL_URL)],
            [InlineKeyboardButton(text="🏠 К расписанию", callback_data="home")],
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки почты", callback_data="mail_settings"
                )
            ],
        ]
    )


def _body_chunks(value: str, limit: int = TELEGRAM_TEXT_LIMIT) -> tuple[str, ...]:
    paragraphs = value.splitlines()
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        line = paragraph + "\n"
        while len(line) > limit:
            available = limit - len(current)
            if available > 0:
                current += line[:available]
                line = line[available:]
            chunks.append(current.rstrip())
            current = ""
        if len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.rstrip())
    return tuple(chunks) or ("Текст письма отсутствует.",)


async def _deliver_pending(bot: Bot) -> None:
    async with async_session_factory() as session:
        pending = await pending_mail_notifications(session)
    for notification in pending:
        received = ""
        if notification.received_at is not None:
            received = (
                f"\n🕒 {notification.received_at.astimezone(MOSCOW):%d.%m.%Y %H:%M}"
            )
        header = (
            "📨 <b>Новое письмо СПбГУ</b>\n\n"
            f"<b>От:</b> {escape(notification.sender)}\n"
            f"<b>Тема:</b> {escape(notification.subject)}"
            f"{received}"
        )
        body = (
            notification.body_text
            or "Текст письма отсутствует или его не удалось прочитать."
        )
        if notification.body_truncated:
            body += "\n\n[Письмо сокращено — полностью его можно открыть в почте.]"
        chunks = _body_chunks(body)
        try:
            await bot.send_message(
                notification.telegram_id, header, parse_mode=ParseMode.HTML
            )
            for index, chunk in enumerate(chunks):
                await bot.send_message(
                    notification.telegram_id,
                    escape(chunk),
                    reply_markup=_mail_keyboard() if index == len(chunks) - 1 else None,
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            logger.exception(
                "Could not deliver queued mail notification id=%s",
                notification.id,
            )
            continue
        async with async_session_factory.begin() as session:
            await mark_mail_notified(session, notification.id)


async def _poll_account(bot: Bot, account: MailAccountConfig) -> None:
    settings = get_settings()
    telegram_id = account.telegram_id
    try:
        if not settings.mail_credentials_key:
            raise ValueError("Mail credential encryption is not configured")
        password = decrypt_app_password(
            account.encrypted_app_password,
            telegram_id,
            settings.mail_credentials_key,
        )
        cursor, messages = await asyncio.to_thread(
            fetch_new_messages,
            account.imap_host,
            account.imap_port,
            account.address,
            password,
            MailboxCursor(
                account.uid_validity,
                account.last_seen_uid,
            ),
        )
        password = ""
        async with async_session_factory.begin() as session:
            await record_mail_poll(session, telegram_id, cursor, messages)
    except StudentMailAuthenticationError:
        error = "Пароль почтового подключения больше не принимается"
        async with async_session_factory.begin() as session:
            await record_mail_failure(session, telegram_id, error)
            notify = await should_notify_mail_error(session, telegram_id)
        if notify:
            await bot.send_message(
                telegram_id,
                "⚠️ <b>Почта СПбГУ не обновляется</b>\n\n"
                "Пароль подключения больше не принимается. Откройте настройки и "
                "подключите "
                "почту заново.",
                reply_markup=_mail_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            async with async_session_factory.begin() as session:
                await mark_mail_error_notified(session, telegram_id)
    except (StudentMailError, ValueError) as exc:
        async with async_session_factory.begin() as session:
            await record_mail_failure(session, telegram_id, str(exc))
        logger.warning("Student mail poll failed telegram_id=%s: %s", telegram_id, exc)


async def poll_student_mail(bot: Bot | None) -> None:
    settings = get_settings()
    if bot is None or not settings.mail_credentials_key:
        return
    async with async_session_factory() as session:
        accounts = await enabled_mail_accounts(session)
    for account in accounts:
        try:
            await _poll_account(bot, account)
        except Exception:
            logger.exception(
                "Unexpected student mail failure telegram_id=%s", account.telegram_id
            )
    await _deliver_pending(bot)
