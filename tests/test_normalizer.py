from datetime import datetime

from app.database.models import ActivityType, DeliveryMode
from app.schedule.normalizer import normalize_event
from app.schedule.source_models import StudyEvent


def test_normalizes_cancelled_offline_lecture() -> None:
    event = StudyEvent.model_validate(
        {
            "Start": "2026-09-01T10:00:00+03:00",
            "End": "2026-09-01T11:35:00+03:00",
            "Subject": "Алгебра, лекция",
            "LocationsDisplayText": "Университетский проспект, д. 35, ауд. 212Д",
            "EducatorsDisplayText": "Иванов И. И.",
            "IsCancelled": True,
            "EducatorIds": [{"Item1": 1312, "Item2": "Иванов Иван Иванович"}],
        }
    )

    lesson = normalize_event(474999, event)

    assert lesson.starts_at == datetime.fromisoformat("2026-09-01T10:00:00+03:00")
    assert lesson.subject == "Алгебра"
    assert lesson.activity_type is ActivityType.lecture
    assert lesson.delivery_mode is DeliveryMode.offline
    assert lesson.building_alias == "ПМ-ПУ"
    assert lesson.room == "212Д"
    assert lesson.teacher_names == ("Иванов Иван Иванович",)
    assert lesson.is_cancelled is True


def test_detects_hybrid_lesson() -> None:
    event = StudyEvent.model_validate(
        {
            "Start": "2026-09-01T12:00:00+03:00",
            "End": "2026-09-01T13:35:00+03:00",
            "Subject": "Анализ данных, практическое занятие",
            "LocationsDisplayText": (
                "Университетский проспект, д. 28, ауд. 404; "
                "дистанционно с применением информационно-коммуникационных технологий"
            ),
        }
    )

    lesson = normalize_event(474999, event)

    assert lesson.subject == "Анализ данных"
    assert lesson.activity_type is ActivityType.practical
    assert lesson.delivery_mode is DeliveryMode.hybrid
    assert lesson.building_alias == "МАТМЕХ"


def test_assumes_moscow_timezone_when_source_datetime_has_no_offset() -> None:
    event = StudyEvent.model_validate(
        {
            "Start": "2026-09-01T10:00:00",
            "End": "2026-09-01T11:35:00",
            "Subject": "Алгебра, лекция",
        }
    )

    lesson = normalize_event(474999, event)

    assert lesson.starts_at.isoformat() == "2026-09-01T10:00:00+03:00"
