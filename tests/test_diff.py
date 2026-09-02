from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

from app.database.models import ActivityType, ChangeKind, DeliveryMode
from app.schedule.diff import compare_schedules
from app.schedule.normalizer import NormalizedLesson


def lesson(**overrides: object) -> NormalizedLesson:
    starts_at = datetime.fromisoformat("2026-09-01T10:00:00+03:00")
    defaults: dict[str, object] = {
        "group_source_id": 474999,
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(minutes=95),
        "subject": "Алгебра",
        "subject_normalized": "алгебра",
        "activity_type": ActivityType.lecture,
        "delivery_mode": DeliveryMode.offline,
        "location_text": "Университетский проспект, д. 35, ауд. 212Д",
        "building_alias": "ПМ-ПУ",
        "room": "212Д",
        "teacher_names": ("Иванов И. И.",),
        "is_cancelled": False,
        "source_marked_time_changed": False,
        "source_marked_location_changed": False,
        "source_marked_teacher_changed": False,
        "source_payload": {},
    }
    defaults.update(overrides)
    return NormalizedLesson(**cast(dict[str, Any], defaults))


def test_detects_cancellation_without_treating_it_as_removal() -> None:
    before = lesson()
    after = replace(before, is_cancelled=True)

    changes = compare_schedules([before], [after])

    assert [change.kind for change in changes] == [ChangeKind.cancelled]


def test_detects_multiple_fields_changed_for_same_lesson() -> None:
    before = lesson()
    after = replace(
        before,
        starts_at=before.starts_at + timedelta(hours=2),
        ends_at=before.ends_at + timedelta(hours=2),
        location_text="Университетский проспект, д. 28, ауд. 404",
        building_alias="МАТМЕХ",
        room="404",
        teacher_names=("Петров П. П.",),
    )

    changes = compare_schedules([before], [after])

    assert {change.kind for change in changes} == {
        ChangeKind.time_changed,
        ChangeKind.location_changed,
        ChangeKind.teacher_changed,
    }


def test_added_and_removed_are_reported() -> None:
    removed = lesson(subject="Алгебра", subject_normalized="алгебра")
    added = lesson(subject="Статистика", subject_normalized="статистика")

    changes = compare_schedules([removed], [added])

    assert {change.kind for change in changes} == {ChangeKind.removed, ChangeKind.added}
