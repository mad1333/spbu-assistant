import uuid
from datetime import datetime

from app.database.models import ActivityType, DeliveryMode
from app.telegram.presentation import (
    apply_english_subgroup,
    english_subgroup_key,
    format_lesson,
)
from app.telegram.types import ScheduleLesson


def lesson(subject: str, teacher: str, *, cancelled: bool = False) -> ScheduleLesson:
    return ScheduleLesson(
        lesson_id=uuid.uuid4(),
        starts_at=datetime.fromisoformat("2026-09-09T11:15:00+03:00"),
        ends_at=datetime.fromisoformat("2026-09-09T12:50:00+03:00"),
        subject=subject,
        activity_type=ActivityType.practical,
        delivery_mode=DeliveryMode.offline,
        location_text="Университетский проспект, д. 35, 329",
        building_alias="ПМ-ПУ",
        room="329",
        teacher_names=(teacher,),
        is_cancelled=cancelled,
        observed_at=datetime.fromisoformat("2026-08-27T09:00:00+03:00"),
    )


def test_selected_english_subgroup_hides_parallel_options() -> None:
    first = lesson("Траектория 2 (А2 – В2). Английский язык", "Малькевич Т. А.")
    second = lesson("Траектория 2 (А2 – В2). Английский язык", "Семенова Ю. О.")
    common = lesson("Английский язык", "Соболев И. А.")

    filtered = apply_english_subgroup(
        (first, second, common),
        english_subgroup_key(second),
    )

    assert filtered == (second, common)


def test_cancelled_lesson_is_visible_and_struck_out() -> None:
    cancelled = lesson("Алгебра", "Утешев А. Ю.", cancelled=True)

    text = format_lesson(cancelled)

    assert "❌ <s>Алгебра</s>" in text
    assert "оставлено в расписании" in text
