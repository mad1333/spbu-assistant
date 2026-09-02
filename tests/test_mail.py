from datetime import UTC, datetime, timedelta

import pytest

from app.mail.client import (
    MailboxCursor,
    _parse_message,
    fetch_new_messages,
    initial_cursor,
    send_message,
)
from app.mail.crypto import decrypt_app_password, encrypt_app_password
from app.mail.setup import mail_setup_html, mail_setup_success_html
from app.mail.tokens import issue_mail_setup_token, verify_mail_setup_token
from app.mail.worker import _mail_keyboard

SECRET = "mail-test-secret-that-is-at-least-thirty-two-characters"


def test_mail_notification_has_schedule_return_button() -> None:
    keyboard = _mail_keyboard()
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "home" in callbacks


def test_mail_credentials_are_encrypted_and_bound_to_user() -> None:
    encrypted = encrypt_app_password("dedicated-app-password", 12345, SECRET)
    assert "dedicated-app-password" not in encrypted
    assert decrypt_app_password(encrypted, 12345, SECRET) == "dedicated-app-password"
    with pytest.raises(ValueError):
        decrypt_app_password(encrypted, 54321, SECRET)


def test_mail_setup_token_expires_and_rejects_tampering() -> None:
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    token = issue_mail_setup_token(12345, 7, SECRET, now=now)
    access = verify_mail_setup_token(token, SECRET, now=now + timedelta(minutes=14))
    assert (access.telegram_id, access.generation) == (12345, 7)
    with pytest.raises(ValueError):
        verify_mail_setup_token(token, SECRET, now=now + timedelta(minutes=16))
    with pytest.raises(ValueError):
        verify_mail_setup_token(
            token[:-1] + ("A" if token[-1] != "A" else "B"), SECRET, now=now
        )


class FakeImap:
    def __init__(self, _host: str, _port: int, *, timeout: int) -> None:
        assert timeout == 15
        self.logged_out = False

    def login(self, address: str, password: str) -> tuple[str, list[bytes]]:
        assert address == "st012345@student.spbu.ru"
        assert password == "secret"
        return "OK", []

    def select(self, mailbox: str, *, readonly: bool) -> tuple[str, list[bytes]]:
        assert mailbox == "INBOX"
        assert readonly is True
        return "OK", [b"2"]

    def response(self, name: str) -> tuple[str, list[bytes]]:
        assert name == "UIDVALIDITY"
        return "UIDVALIDITY", [b"77"]

    def uid(self, command: str, *_args: object) -> tuple[str, list[object]]:
        if command == "search" and _args[-1] == "ALL":
            return "OK", [b"10 12"]
        if command == "search":
            return "OK", [b"13 14"]
        uid = int(str(_args[0]))
        raw = (
            "From: =?utf-8?b?0JjQstCw0L0=?= <teacher@spbu.ru>\r\n"
            f"Subject: Новость {uid}\r\n"
            "Date: Thu, 27 Aug 2026 15:30:00 +0300\r\n"
            f"Message-ID: <message-{uid}@spbu.ru>\r\n\r\n"
        ).encode()
        return "OK", [(b"headers", raw), b")"]

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return "BYE", []


def test_imap_cursor_avoids_old_mail_and_reads_only_new_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.mail.client.imaplib.IMAP4_SSL", FakeImap)
    cursor = initial_cursor(
        "imap.mail.ru",
        993,
        "st012345@student.spbu.ru",
        "secret",
    )
    assert cursor == MailboxCursor("77", 12)

    next_cursor, messages = fetch_new_messages(
        "imap.mail.ru",
        993,
        "st012345@student.spbu.ru",
        "secret",
        cursor,
    )
    assert next_cursor == MailboxCursor("77", 14)
    assert [message.uid for message in messages] == [13, 14]
    assert messages[0].sender == "Иван <teacher@spbu.ru>"
    assert messages[0].subject == "Новость 13"
    assert messages[0].received_at == datetime(2026, 8, 27, 12, 30, tzinfo=UTC)
    assert messages[0].body_text is None


def test_mail_setup_pages_do_not_echo_credentials_and_escape_addresses() -> None:
    page = mail_setup_html("safe-token")
    assert 'type="password"' in page
    assert "safe-token" in page
    success = mail_setup_success_html("<unsafe>@student.spbu.ru")
    assert "<unsafe>" not in success
    assert "&lt;unsafe&gt;" in success


def test_html_mail_is_converted_to_safe_readable_text() -> None:
    raw = (
        "From: teacher@spbu.ru\r\n"
        "Subject: Материалы\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<h2>Здравствуйте!</h2><p>Откройте <a href='https://spbu.ru/task'>задание</a>."
        "</p>"
    ).encode()
    parsed = _parse_message(15, raw)
    assert "Здравствуйте!" in (parsed.body_text or "")
    assert "задание (https://spbu.ru/task)" in (parsed.body_text or "")
    assert "<h2>" not in (parsed.body_text or "")


class FakeSmtp:
    sent = None

    def __init__(self, host: str, port: int, *, timeout: int) -> None:
        assert (host, port, timeout) == ("smtp.mail.ru", 465, 20)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def login(self, address: str, password: str) -> None:
        assert address == "st012345@student.spbu.ru"
        assert password == "secret"

    def send_message(self, message: object) -> dict[str, object]:
        FakeSmtp.sent = message
        return {}


def test_smtp_sends_plain_and_formatted_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.mail.client.smtplib.SMTP_SSL", FakeSmtp)
    send_message(
        "smtp.mail.ru",
        465,
        "st012345@student.spbu.ru",
        "secret",
        "teacher@spbu.ru",
        "Вопрос",
        "Здравствуйте!",
        "<b>Здравствуйте!</b>",
    )
    assert FakeSmtp.sent["To"] == "teacher@spbu.ru"
    assert FakeSmtp.sent["Subject"] == "Вопрос"
    assert FakeSmtp.sent.is_multipart()
