from datetime import UTC, datetime

from app.config import Settings
from app.telegram.admin import (
    AdminOverview,
    AdminUser,
    GroupUsage,
    format_admin_overview,
    format_admin_users,
    format_group_usage,
)
from app.telegram.keyboards import admin_keyboard


def test_admin_ids_are_parsed() -> None:
    settings = Settings(telegram_admin_ids="123, 456")

    assert settings.admin_ids == (123, 456)


def test_admin_overview_is_formatted() -> None:
    overview = AdminOverview(10, 3, 7, 9, 2, 4, 5)

    text = format_admin_overview(overview)

    assert "Пользователей: <b>10</b>" in text
    assert "Apple — <b>4</b>" in text
    assert "Google — <b>5</b>" in text


def test_admin_users_escape_personal_data() -> None:
    users = (
        AdminUser(
            telegram_id=123,
            username="student",
            display_name="Иван <script>",
            group_name="Группа 24.Б10-мм & тест",
            last_active_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
            interaction_count=12,
            mail_connected=True,
        ),
    )

    text = format_admin_users(users, 0)

    assert "Иван &lt;script&gt;" in text
    assert "Группа 24.Б10-мм &amp; тест" in text
    assert "почта ✓" in text
    assert "<code>123</code>" in text


def test_group_usage_is_formatted() -> None:
    text = format_group_usage((GroupUsage("Группа 24.Б10-мм", 2),))

    assert "Группа 24.Б10-мм — <b>2</b>" in text


def test_admin_keyboard_returns_to_schedule() -> None:
    callbacks = {
        button.callback_data
        for row in admin_keyboard().inline_keyboard
        for button in row
    }

    assert "home" in callbacks
