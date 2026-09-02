from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class MailSetupAccess:
    telegram_id: int
    generation: int
    expires_at: datetime


def issue_mail_setup_token(
    telegram_id: int,
    generation: int,
    secret: str,
    *,
    now: datetime | None = None,
    lifetime: timedelta = timedelta(minutes=15),
) -> str:
    if len(secret) < 32:
        raise ValueError(
            "Mail setup signing secret must contain at least 32 characters"
        )
    issued_at = now or datetime.now(UTC)
    expires = int((issued_at + lifetime).timestamp())
    payload = f"mail:{telegram_id}:{generation}:{expires}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[:20]
    return base64.urlsafe_b64encode(payload + b"." + signature).decode().rstrip("=")


def verify_mail_setup_token(
    token: str,
    secret: str,
    *,
    now: datetime | None = None,
) -> MailSetupAccess:
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
        payload, signature = decoded.rsplit(b".", 1)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[:20]
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid mail setup token signature")
        prefix, telegram_id_text, generation_text, expires_text = (
            payload.decode().split(":", 3)
        )
        if prefix != "mail":
            raise ValueError("Invalid mail setup token purpose")
        expires_at = datetime.fromtimestamp(int(expires_text), UTC)
        if expires_at <= (now or datetime.now(UTC)):
            raise ValueError("Mail setup token expired")
        return MailSetupAccess(int(telegram_id_text), int(generation_text), expires_at)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid mail setup token") from exc
