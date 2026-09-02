from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalendarAccess:
    telegram_id: int
    generation: int


def issue_calendar_token(telegram_id: int, generation: int, secret: str) -> str:
    if len(secret) < 32:
        raise ValueError("Calendar signing secret must contain at least 32 characters")
    payload = f"{telegram_id}:{generation}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[:20]
    return base64.urlsafe_b64encode(payload + b"." + signature).decode().rstrip("=")


def verify_calendar_token(token: str, secret: str) -> CalendarAccess:
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
        payload, signature = decoded.rsplit(b".", 1)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()[:20]
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid calendar token signature")
        telegram_id_text, generation_text = payload.decode().split(":", 1)
        return CalendarAccess(int(telegram_id_text), int(generation_text))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid calendar token") from exc
