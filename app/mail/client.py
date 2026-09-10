from __future__ import annotations

import imaplib
import re
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import formataddr, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser


class StudentMailError(RuntimeError):
    """A safe-to-handle mail connection failure."""


class StudentMailAuthenticationError(StudentMailError):
    """The app password was rejected."""


@dataclass(frozen=True, slots=True)
class MailboxCursor:
    uid_validity: str
    last_uid: int


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    uid: int
    message_id: str | None
    sender: str
    subject: str
    received_at: datetime | None
    body_text: str | None
    body_truncated: bool


MAX_INCOMING_BYTES = 1_000_000
MAX_BODY_CHARACTERS = 900_000


class _ReadableHtmlParser(HTMLParser):
    """Turn an HTML mail body into safe, compact text suitable for Telegram."""

    BLOCK_TAGS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a" and self.links:
            href = self.links.pop()
            if href and href.startswith(("http://", "https://", "mailto:")):
                self.parts.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts).replace("\xa0", " ")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def _decode_header(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    try:
        return str(make_header(decode_header(value))).strip() or fallback
    except (LookupError, UnicodeDecodeError):
        return value.strip() or fallback


def _uid_validity(client: imaplib.IMAP4_SSL) -> str:
    response = client.response("UIDVALIDITY")[1]
    if not response or response[0] is None:
        raise StudentMailError("IMAP server did not provide UIDVALIDITY")
    value = response[0]
    return value.decode() if isinstance(value, bytes) else str(value)


def _uids(data: list[bytes | None]) -> list[int]:
    if not data or not data[0]:
        return []
    return [int(value) for value in data[0].split()]


def _login(
    host: str,
    port: int,
    address: str,
    app_password: str,
) -> imaplib.IMAP4_SSL:
    try:
        client = imaplib.IMAP4_SSL(host, port, timeout=15)
        client.login(address, app_password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            client.logout()
            raise StudentMailError("Inbox is not available")
        return client
    except imaplib.IMAP4.error as exc:
        raise StudentMailAuthenticationError("App password was rejected") from exc
    except (OSError, TimeoutError) as exc:
        raise StudentMailError("Mail server is temporarily unavailable") from exc


def initial_cursor(
    host: str, port: int, address: str, app_password: str
) -> MailboxCursor:
    client = _login(host, port, address, app_password)
    try:
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise StudentMailError("Could not read inbox state")
        uids = _uids(data)
        return MailboxCursor(_uid_validity(client), max(uids, default=0))
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass


def _message_body(message: Message) -> tuple[str | None, bool]:
    candidates: list[tuple[int, str]] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()
        if disposition == "attachment" or content_type not in {
            "text/plain",
            "text/html",
        }:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError, ValueError):
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            content = payload.decode(
                part.get_content_charset() or "utf-8", errors="replace"
            )
        if not isinstance(content, str):
            continue
        if content_type == "text/html":
            parser = _ReadableHtmlParser()
            parser.feed(content)
            content = parser.text()
            priority = 1
        else:
            content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
            priority = 0
        if content:
            candidates.append((priority, content))
    if not candidates:
        return None, False
    text = min(candidates, key=lambda item: item[0])[1]
    truncated = len(text) > MAX_BODY_CHARACTERS
    return text[:MAX_BODY_CHARACTERS], truncated


def _parse_message(
    uid: int, raw_message: bytes, *, partial: bool = False
) -> IncomingMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    name, address = parseaddr(message.get("From", ""))
    decoded_name = _decode_header(name, "")
    sender = (
        f"{decoded_name} <{address}>"
        if decoded_name and address
        else address or "Неизвестный отправитель"
    )
    received_at = None
    if message.get("Date"):
        try:
            received_at = parsedate_to_datetime(message["Date"])
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=UTC)
            received_at = received_at.astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            received_at = None
    body_text, body_truncated = _message_body(message)
    return IncomingMessage(
        uid=uid,
        message_id=(message.get("Message-ID") or "").strip() or None,
        sender=sender[:998],
        subject=_decode_header(message.get("Subject"), "Без темы")[:998],
        received_at=received_at,
        body_text=body_text,
        body_truncated=body_truncated or partial,
    )


def _fetch_payload(payload: list[object]) -> bytes | None:
    return next(
        (
            item[1]
            for item in payload
            if isinstance(item, tuple) and isinstance(item[1], bytes)
        ),
        None,
    )


def fetch_new_messages(
    host: str,
    port: int,
    address: str,
    app_password: str,
    cursor: MailboxCursor,
    *,
    limit: int = 50,
) -> tuple[MailboxCursor, tuple[IncomingMessage, ...]]:
    client = _login(host, port, address, app_password)
    try:
        uid_validity = _uid_validity(client)
        if uid_validity != cursor.uid_validity:
            status, data = client.uid("search", None, "ALL")
            if status != "OK":
                raise StudentMailError("Could not reset inbox state")
            current = _uids(data)
            return MailboxCursor(uid_validity, max(current, default=0)), ()

        status, data = client.uid("search", None, f"UID {cursor.last_uid + 1}:*")
        if status != "OK":
            raise StudentMailError("Could not search for new messages")
        message_uids = [uid for uid in _uids(data) if uid > cursor.last_uid][:limit]
        messages: list[IncomingMessage] = []
        last_uid = cursor.last_uid
        for uid in message_uids:
            status, payload = client.uid(
                "fetch",
                str(uid),
                f"(BODY.PEEK[]<0.{MAX_INCOMING_BYTES}>)",
            )
            if status != "OK":
                continue
            raw = _fetch_payload(payload)
            if raw is not None:
                messages.append(
                    _parse_message(uid, raw, partial=len(raw) >= MAX_INCOMING_BYTES)
                )
            last_uid = max(last_uid, uid)
        return MailboxCursor(uid_validity, last_uid), tuple(messages)
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass


def send_message(
    host: str,
    port: int,
    address: str,
    app_password: str,
    recipient: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> str:
    """Send one message through the connected SPbU mailbox."""
    message = EmailMessage()
    message["From"] = formataddr(("Студент СПбГУ", address))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body_text)
    if body_html and body_html != body_text:
        message.add_alternative(body_html, subtype="html")
    try:
        with smtplib.SMTP_SSL(host, port, timeout=20) as client:
            client.login(address, app_password)
            refused = client.send_message(message)
        if refused:
            raise StudentMailError("Mail server refused the recipient")
    except smtplib.SMTPAuthenticationError as exc:
        raise StudentMailAuthenticationError("App password was rejected") from exc
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        raise StudentMailError("Mail server is temporarily unavailable") from exc
    return (message.get("Message-ID") or "").strip()
