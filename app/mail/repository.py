from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import MailNotification, StudentMailAccount, TelegramUser
from app.mail.client import IncomingMessage, MailboxCursor


@dataclass(frozen=True, slots=True)
class MailAccountStatus:
    connected: bool
    address: str | None
    enabled: bool
    last_checked_at: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class MailAccountConfig:
    telegram_id: int
    address: str
    encrypted_app_password: str
    imap_host: str
    imap_port: int
    uid_validity: str
    last_seen_uid: int


async def mail_account_status(
    session: AsyncSession, telegram_id: int
) -> MailAccountStatus:
    account = await session.get(StudentMailAccount, telegram_id)
    if account is None:
        return MailAccountStatus(False, None, False, None, None)
    return MailAccountStatus(
        True,
        account.address,
        account.enabled,
        account.last_checked_at,
        account.last_error,
    )


async def save_mail_account(
    session: AsyncSession,
    telegram_id: int,
    address: str,
    encrypted_app_password: str,
    host: str,
    port: int,
    cursor: MailboxCursor,
) -> None:
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    now = datetime.now(UTC)
    account = await session.get(StudentMailAccount, telegram_id)
    if account is None:
        account = StudentMailAccount(
            telegram_id=telegram_id,
            address=address,
            encrypted_app_password=encrypted_app_password,
            imap_host=host,
            imap_port=port,
            enabled=True,
            uid_validity=cursor.uid_validity,
            last_seen_uid=cursor.last_uid,
            last_checked_at=now,
            last_error=None,
            consecutive_failures=0,
            last_error_notified_at=None,
            connected_at=now,
            updated_at=now,
        )
        session.add(account)
    else:
        account.address = address
        account.encrypted_app_password = encrypted_app_password
        account.imap_host = host
        account.imap_port = port
        account.enabled = True
        account.uid_validity = cursor.uid_validity
        account.last_seen_uid = cursor.last_uid
        account.last_checked_at = now
        account.last_error = None
        account.consecutive_failures = 0
        account.last_error_notified_at = None
        account.connected_at = now
        account.updated_at = now
        await session.execute(
            delete(MailNotification).where(MailNotification.telegram_id == telegram_id)
        )
    user.mail_setup_generation += 1
    user.updated_at = now


async def disconnect_mail_account(session: AsyncSession, telegram_id: int) -> None:
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        raise LookupError("User was not found")
    account = await session.get(StudentMailAccount, telegram_id)
    if account is not None:
        await session.delete(account)
    user.mail_setup_generation += 1
    user.updated_at = datetime.now(UTC)


async def enabled_mail_accounts(session: AsyncSession) -> tuple[MailAccountConfig, ...]:
    accounts = tuple(
        await session.scalars(
            select(StudentMailAccount)
            .where(
                StudentMailAccount.enabled.is_(True),
                StudentMailAccount.uid_validity.is_not(None),
            )
            .order_by(StudentMailAccount.telegram_id)
        )
    )
    return tuple(
        MailAccountConfig(
            account.telegram_id,
            account.address,
            account.encrypted_app_password,
            account.imap_host,
            account.imap_port,
            account.uid_validity or "",
            account.last_seen_uid,
        )
        for account in accounts
    )


async def mail_account_config(
    session: AsyncSession,
    telegram_id: int,
) -> MailAccountConfig | None:
    account = await session.get(StudentMailAccount, telegram_id)
    if account is None or not account.enabled or account.uid_validity is None:
        return None
    return MailAccountConfig(
        account.telegram_id,
        account.address,
        account.encrypted_app_password,
        account.imap_host,
        account.imap_port,
        account.uid_validity,
        account.last_seen_uid,
    )


async def record_mail_poll(
    session: AsyncSession,
    telegram_id: int,
    cursor: MailboxCursor,
    messages: tuple[IncomingMessage, ...],
) -> None:
    account = await session.get(StudentMailAccount, telegram_id)
    if account is None:
        return
    now = datetime.now(UTC)
    for message in messages:
        exists = await session.scalar(
            select(MailNotification.id).where(
                MailNotification.telegram_id == telegram_id,
                MailNotification.uid_validity == cursor.uid_validity,
                MailNotification.message_uid == message.uid,
            )
        )
        if exists is None:
            session.add(
                MailNotification(
                    telegram_id=telegram_id,
                    uid_validity=cursor.uid_validity,
                    message_uid=message.uid,
                    message_id=message.message_id,
                    sender=message.sender,
                    subject=message.subject,
                    body_text=message.body_text,
                    body_truncated=message.body_truncated,
                    received_at=message.received_at,
                    discovered_at=now,
                    notified_at=None,
                )
            )
    account.uid_validity = cursor.uid_validity
    account.last_seen_uid = cursor.last_uid
    account.last_checked_at = now
    account.last_error = None
    account.consecutive_failures = 0
    account.updated_at = now


async def record_mail_failure(
    session: AsyncSession,
    telegram_id: int,
    message: str,
) -> int:
    account = await session.get(StudentMailAccount, telegram_id)
    if account is None:
        return 0
    account.last_checked_at = datetime.now(UTC)
    account.last_error = message[:512]
    account.consecutive_failures += 1
    account.updated_at = datetime.now(UTC)
    return account.consecutive_failures


async def pending_mail_notifications(
    session: AsyncSession,
) -> tuple[MailNotification, ...]:
    return tuple(
        await session.scalars(
            select(MailNotification)
            .where(MailNotification.notified_at.is_(None))
            .order_by(MailNotification.discovered_at, MailNotification.message_uid)
            .limit(200)
        )
    )


async def mark_mail_notified(
    session: AsyncSession,
    notification_id: object,
) -> None:
    notification = await session.get(MailNotification, notification_id)
    if notification is not None:
        notification.notified_at = datetime.now(UTC)
        notification.body_text = None


async def should_notify_mail_error(session: AsyncSession, telegram_id: int) -> bool:
    account = await session.get(StudentMailAccount, telegram_id)
    if account is None or account.consecutive_failures < 3:
        return False
    if account.last_error_notified_at is None:
        return True
    return (datetime.now(UTC) - account.last_error_notified_at).total_seconds() >= 86400


async def mark_mail_error_notified(session: AsyncSession, telegram_id: int) -> None:
    account = await session.get(StudentMailAccount, telegram_id)
    if account is not None:
        account.last_error_notified_at = datetime.now(UTC)
