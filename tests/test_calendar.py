import uuid
from datetime import datetime

import pytest

from app.calendar.feed import (
    build_icalendar,
    calendar_setup_html,
    google_calendar_setup_html,
)
from app.calendar.tokens import issue_calendar_token, verify_calendar_token
from app.database.models import ActivityType, DeliveryMode
from app.telegram.types import GroupOption, ScheduleLesson

SECRET = "a-very-long-calendar-signing-secret-for-tests"


def test_calendar_token_is_signed_and_revocable_by_generation() -> None:
    token = issue_calendar_token(123456789, 4, SECRET)

    access = verify_calendar_token(token, SECRET)

    assert access.telegram_id == 123456789
    assert access.generation == 4
    with pytest.raises(ValueError):
        verify_calendar_token(token[:-1] + "A", SECRET)


def test_cancelled_feed_keeps_event_with_cross_and_cancelled_status() -> None:
    lesson = ScheduleLesson(
        lesson_id=uuid.uuid4(),
        starts_at=datetime.fromisoformat("2026-09-01T13:40:00+03:00"),
        ends_at=datetime.fromisoformat("2026-09-01T15:15:00+03:00"),
        subject="Алгебра",
        activity_type=ActivityType.lecture,
        delivery_mode=DeliveryMode.offline,
        location_text="Университетский проспект, д. 35, лит. Д, 212Д",
        building_alias="ПМ-ПУ",
        room="212Д",
        teacher_names=("Утешев А. Ю., профессор",),
        is_cancelled=True,
        observed_at=datetime.fromisoformat("2026-08-27T09:00:00+03:00"),
    )
    group = GroupOption(uuid.uuid4(), 474999, "Группа 26.Б15-пу")

    cancelled = build_icalendar(
        "cancelled",
        group,
        (lesson,),
        base_url="https://timetable.spbu.ru",
    )
    lectures = build_icalendar(
        "lecture",
        group,
        (lesson,),
        base_url="https://timetable.spbu.ru",
    )

    assert "SUMMARY:❌ Алгебра" in cancelled
    assert "STATUS:CANCELLED" in cancelled
    assert str(lesson.lesson_id) not in lectures


def test_setup_page_contains_install_and_removal_instructions() -> None:
    html = calendar_setup_html("signed-token", "https://schedule.example.com")

    assert "webcal://schedule.example.com/calendar/signed-token/lecture.ics" in html
    assert "Удалить календарь" in html
    assert "Отписаться" in html


def test_google_setup_has_subscribe_actions_and_manual_urls() -> None:
    html = google_calendar_setup_html("token-123", "https://bot.example")

    assert "calendar.google.com/calendar/render?cid=" in html
    assert "https%3A%2F%2Fbot.example%2Fcalendar%2Ftoken-123%2Flecture.ics" in html
    assert "Добавить по URL" in html
    assert "Отказаться от подписки" in html
