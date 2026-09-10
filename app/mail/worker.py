from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

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
MARKDOWN_RESERVED = re.compile(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])")


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


def _escape_markdown(value: str) -> str:
    return MARKDOWN_RESERVED.sub(r"\\\1", value)


def _mail_header(
    sender: str,
    subject: str,
    received_at: datetime | None,
) -> str:
    sender_text = _escape_markdown(sender[:500])
    subject_text = _escape_markdown(subject[:700])
    received = ""
    if received_at is not None:
        value = received_at.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")
        received = f"\n🕒 {_escape_markdown(value)}"
    return (
        "📨 *Новое письмо СПбГУ*\n\n"
        f"*От:* {sender_text}\n"
        f"*Тема:* {subject_text}"
        f"{received}"
    )


def _mail_message(
    sender: str,
    subject: str,
    received_at: datetime | None,
    body_text: str | None,
) -> str:
    header = _mail_header(sender, subject, received_at)
    body = body_text or "Текст письма отсутствует или его не удалось прочитать."
    return header + "\n\n" + _escape_markdown(body)


def _mail_document_text(
    sender: str,
    subject: str,
    received_at: datetime | None,
    body_text: str | None,
    body_truncated: bool,
) -> str:
    received = (
        received_at.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")
        if received_at is not None
        else "не указано"
    )
    body = body_text or "Текст письма отсутствует или его не удалось прочитать."
    parts = [
        "Новое письмо СПбГУ",
        "",
        f"От: {sender}",
        f"Тема: {subject}",
        f"Получено: {received}",
        "",
        body,
    ]
    if body_truncated:
        parts.extend(
            (
                "",
                "Почтовый сервер передал только часть слишком большого письма.",
                "Полная версия остаётся доступна в почтовом ящике.",
            )
        )
    return "\n".join(parts)


def _mail_filename(subject: str, message_uid: int) -> str:
    clean = re.sub(r"[^\w .()-]+", "_", subject).strip(" .")[:80]
    return f"{clean or 'Письмо'}-{message_uid}.txt"


async def _deliver_pending(bot: Bot) -> None:
    async with async_session_factory() as session:
        pending = await pending_mail_notifications(session)
    for notification in pending:
        message = _mail_message(
            notification.sender,
            notification.subject,
            notification.received_at,
            notification.body_text,
        )
        try:
            if len(message) <= TELEGRAM_TEXT_LIMIT and not notification.body_truncated:
                await bot.send_message(
                    notification.telegram_id,
                    message,
                    reply_markup=_mail_keyboard(),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            else:
                document_text = _mail_document_text(
                    notification.sender,
                    notification.subject,
                    notification.received_at,
                    notification.body_text,
                    notification.body_truncated,
                )
                document = BufferedInputFile(
                    document_text.encode("utf-8"),
                    filename=_mail_filename(
                        notification.subject,
                        notification.message_uid,
                    ),
                )
                caption = _mail_header(
                    notification.sender,
                    notification.subject,
                    notification.received_at,
                )
                caption += "\n\n📎 Полный текст приложен одним файлом\\."
                await bot.send_document(
                    notification.telegram_id,
                    document,
                    caption=caption,
                    reply_markup=_mail_keyboard(),
                    parse_mode=ParseMode.MARKDOWN_V2,
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
