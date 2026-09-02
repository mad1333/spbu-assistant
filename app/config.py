from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(name: str) -> str | None:
    path = Path("/run/secrets") / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = (
        "postgresql+asyncpg://spbu:development@localhost:5432/spbu_assistant"
    )
    public_base_url: str = "http://localhost:8000"
    spbu_base_url: HttpUrl = Field(default="https://timetable.spbu.ru")
    spbu_request_timeout_seconds: float = 10.0
    timetable_poll_interval_seconds: int = 600
    on_demand_freshness_seconds: int = 60
    group_catalog_refresh_interval_seconds: int = 21600
    initial_group_ids: str = "474999"

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_admin_ids: str = ""
    token_signing_key: str | None = None
    mail_credentials_key: str | None = None
    mail_imap_host: str = "imap.mail.ru"
    mail_imap_port: int = 993
    mail_smtp_host: str = "smtp.mail.ru"
    mail_smtp_port: int = 465
    mail_poll_interval_seconds: int = 60

    @property
    def configured_group_ids(self) -> tuple[int, ...]:
        return tuple(
            int(value.strip())
            for value in self.initial_group_ids.split(",")
            if value.strip()
        )

    @property
    def admin_ids(self) -> tuple[int, ...]:
        return tuple(
            int(value.strip())
            for value in self.telegram_admin_ids.split(",")
            if value.strip()
        )

    def model_post_init(self, __context: object) -> None:
        self.telegram_bot_token = self.telegram_bot_token or _read_secret(
            "telegram_bot_token"
        )
        self.telegram_webhook_secret = self.telegram_webhook_secret or _read_secret(
            "telegram_webhook_secret"
        )
        self.token_signing_key = self.token_signing_key or _read_secret(
            "token_signing_key"
        )
        self.mail_credentials_key = self.mail_credentials_key or _read_secret(
            "mail_credentials_key"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
