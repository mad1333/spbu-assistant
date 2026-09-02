import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from app.calendar.feed import (
    VALID_KINDS,
    build_icalendar,
    calendar_setup_html,
    google_calendar_setup_html,
)
from app.calendar.tokens import CalendarAccess, verify_calendar_token
from app.config import get_settings
from app.database.models import TelegramUser
from app.database.session import async_session_factory
from app.mail.client import (
    StudentMailAuthenticationError,
    StudentMailError,
    initial_cursor,
)
from app.mail.crypto import encrypt_app_password
from app.mail.repository import save_mail_account
from app.mail.setup import mail_setup_html, mail_setup_success_html
from app.mail.tokens import MailSetupAccess, verify_mail_setup_token
from app.telegram.presentation import apply_english_subgroup
from app.telegram.repository import calendar_lessons, get_existing_user
from app.telegram.runtime import create_runtime
from app.telegram.types import UserContext

settings = get_settings()
telegram_runtime = create_runtime()
logger = logging.getLogger(__name__)
STUDENT_MAIL_PATTERN = re.compile(r"^st\d+@student\.spbu\.ru$", re.IGNORECASE)
MAIL_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if telegram_runtime and settings.app_env == "production":
        bot, dispatcher = telegram_runtime
        await bot.set_webhook(
            f"{settings.public_base_url.rstrip('/')}/telegram/webhook",
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    yield
    if telegram_runtime:
        await telegram_runtime[0].session.close()


app = FastAPI(
    title="SPbU Assistant API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "time": datetime.now(UTC).isoformat(),
    }


@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    if telegram_runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram is not configured"
        )
    if (
        settings.telegram_webhook_secret
        and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook secret")
    bot, dispatcher = telegram_runtime
    update = Update.model_validate(await request.json(), context={"bot": bot})
    try:
        await dispatcher.feed_update(bot, update)
    except TelegramBadRequest as exc:
        message = str(exc).casefold()
        if "query is too old" not in message and "query id is invalid" not in message:
            raise
        logger.warning("Discarding an expired Telegram callback query")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _decode_mail_token(token: str) -> MailSetupAccess:
    if not settings.token_signing_key or not settings.mail_credentials_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Student mail is not configured"
        )
    try:
        return verify_mail_setup_token(token, settings.token_signing_key)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Setup link is invalid or expired"
        ) from exc


async def _mail_setup_access(token: str) -> MailSetupAccess:
    access = _decode_mail_token(token)
    async with async_session_factory() as session:
        user = await session.get(TelegramUser, access.telegram_id)
    if user is None or user.mail_setup_generation != access.generation:
        raise HTTPException(status.HTTP_410_GONE, "Setup link has already been used")
    return access


@app.get("/mail/setup/{token}", response_class=HTMLResponse, include_in_schema=False)
async def student_mail_setup(token: str) -> HTMLResponse:
    await _mail_setup_access(token)
    return HTMLResponse(mail_setup_html(token), headers=MAIL_PAGE_HEADERS)


@app.post("/mail/setup/{token}", response_class=HTMLResponse, include_in_schema=False)
async def student_mail_connect(token: str, request: Request) -> HTMLResponse:
    access = await _mail_setup_access(token)
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Form encoding is required"
        )
    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Form is too large"
        )
    try:
        form = parse_qs(body.decode(), strict_parsing=True)
        address = form["address"][0].strip().lower()
        app_password = form["app_password"][0].strip()
    except (KeyError, UnicodeDecodeError, ValueError, IndexError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid form"
        ) from exc
    if not STUDENT_MAIL_PATTERN.fullmatch(address):
        return HTMLResponse(
            mail_setup_html(token, error="Нужен адрес вида stXXXXXX@student.spbu.ru"),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            headers=MAIL_PAGE_HEADERS,
        )
    if not 6 <= len(app_password) <= 256:
        return HTMLResponse(
            mail_setup_html(token, error="Проверьте пароль почтового подключения"),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            headers=MAIL_PAGE_HEADERS,
        )
    try:
        cursor = await asyncio.to_thread(
            initial_cursor,
            settings.mail_imap_host,
            settings.mail_imap_port,
            address,
            app_password,
        )
    except StudentMailAuthenticationError:
        return HTMLResponse(
            mail_setup_html(
                token,
                error=(
                    "Почтовый сервер отклонил логин или пароль. Проверьте адрес "
                    "и пароль, "
                    "затем попробуйте ещё раз."
                ),
            ),
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=MAIL_PAGE_HEADERS,
        )
    except StudentMailError:
        return HTMLResponse(
            mail_setup_html(
                token, error="Почтовый сервер временно недоступен. Попробуйте позже."
            ),
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers=MAIL_PAGE_HEADERS,
        )
    encrypted = encrypt_app_password(
        app_password,
        access.telegram_id,
        settings.mail_credentials_key or "",
    )
    app_password = ""
    async with async_session_factory.begin() as session:
        user = await session.get(TelegramUser, access.telegram_id, with_for_update=True)
        if user is None or user.mail_setup_generation != access.generation:
            raise HTTPException(
                status.HTTP_410_GONE, "Setup link has already been used"
            )
        await save_mail_account(
            session,
            access.telegram_id,
            address,
            encrypted,
            settings.mail_imap_host,
            settings.mail_imap_port,
            cursor,
        )
    return HTMLResponse(mail_setup_success_html(address), headers=MAIL_PAGE_HEADERS)


def _decode_calendar_token(token: str) -> CalendarAccess:
    if not settings.token_signing_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Calendar is not configured"
        )
    try:
        return verify_calendar_token(token, settings.token_signing_key)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Calendar was not found"
        ) from exc


async def _calendar_user(token: str) -> UserContext:
    access = _decode_calendar_token(token)
    async with async_session_factory() as session:
        user = await get_existing_user(session, access.telegram_id)
    if user is None or user.calendar_generation != access.generation:
        raise HTTPException(status.HTTP_410_GONE, "Calendar access was revoked")
    if user.current_group is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Student group is not selected")
    return user


@app.get(
    "/calendar/setup/{token}", response_class=HTMLResponse, include_in_schema=False
)
async def calendar_setup(token: str) -> HTMLResponse:
    await _calendar_user(token)
    return HTMLResponse(calendar_setup_html(token, settings.public_base_url))


@app.get(
    "/calendar/google/setup/{token}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def google_calendar_setup(token: str) -> HTMLResponse:
    await _calendar_user(token)
    return HTMLResponse(google_calendar_setup_html(token, settings.public_base_url))


@app.get("/calendar/{token}/{kind}.ics", include_in_schema=False)
async def calendar_feed(token: str, kind: str) -> Response:
    if kind not in VALID_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Calendar type was not found")
    user = await _calendar_user(token)
    today = datetime.now(UTC).date()
    async with async_session_factory() as session:
        lessons = await calendar_lessons(
            session,
            user.current_group.id,  # type: ignore[union-attr]
            not_before=today - timedelta(days=30),
            not_after=today + timedelta(days=180),
        )
    lessons = apply_english_subgroup(lessons, user.english_subgroup_key)
    body = build_icalendar(
        kind,
        user.current_group,  # type: ignore[arg-type]
        lessons,
        base_url=str(settings.spbu_base_url),
    )
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=60",
            "Content-Disposition": f'inline; filename="spbu-{kind}.ics"',
        },
    )
