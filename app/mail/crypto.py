from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key(secret: str) -> bytes:
    if len(secret) < 32:
        raise ValueError("Mail credentials secret must contain at least 32 characters")
    return hashlib.sha256(secret.encode()).digest()


def encrypt_app_password(password: str, telegram_id: int, secret: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key(secret)).encrypt(
        nonce,
        password.encode(),
        str(telegram_id).encode(),
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_app_password(value: str, telegram_id: int, secret: str) -> str:
    try:
        decoded = base64.urlsafe_b64decode(value.encode())
        plaintext = AESGCM(_key(secret)).decrypt(
            decoded[:12],
            decoded[12:],
            str(telegram_id).encode(),
        )
        return plaintext.decode()
    except (ValueError, InvalidTag, UnicodeDecodeError) as exc:
        raise ValueError("Stored mail credential cannot be decrypted") from exc
