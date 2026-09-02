from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.database.models import ChangeKind
from app.schedule.normalizer import NormalizedLesson


@dataclass(frozen=True, slots=True)
class LessonChange:
    kind: ChangeKind
    before: NormalizedLesson | None
    after: NormalizedLesson | None
    message: str


def _teacher_set(lesson: NormalizedLesson) -> set[str]:
    return {name.casefold() for name in lesson.teacher_names}


def _match_score(before: NormalizedLesson, after: NormalizedLesson) -> float:
    if before.group_source_id != after.group_source_id:
        return float("-inf")
    if before.subject_normalized != after.subject_normalized:
        return float("-inf")
    if before.activity_type != after.activity_type:
        return float("-inf")
    if before.starts_at.date() != after.starts_at.date():
        return float("-inf")

    score = 50.0
    delta_minutes = abs((before.starts_at - after.starts_at).total_seconds()) / 60
    score += max(0.0, 20.0 - delta_minutes / 15)

    before_teachers = _teacher_set(before)
    after_teachers = _teacher_set(after)
    if before_teachers and after_teachers:
        score += 20.0 if before_teachers & after_teachers else 0.0
    if before.location_text and before.location_text == after.location_text:
        score += 15.0
    return score


def pair_lessons(
    previous: list[NormalizedLesson],
    current: list[NormalizedLesson],
) -> tuple[
    list[tuple[NormalizedLesson, NormalizedLesson]],
    list[NormalizedLesson],
    list[NormalizedLesson],
]:
    candidates: list[tuple[float, int, int]] = []
    for previous_index, before in enumerate(previous):
        for current_index, after in enumerate(current):
            score = _match_score(before, after)
            if score >= 50:
                candidates.append((score, previous_index, current_index))

    pairs: list[tuple[NormalizedLesson, NormalizedLesson]] = []
    matched_previous: set[int] = set()
    matched_current: set[int] = set()
    for _, previous_index, current_index in sorted(candidates, reverse=True):
        if previous_index in matched_previous or current_index in matched_current:
            continue
        matched_previous.add(previous_index)
        matched_current.add(current_index)
        pairs.append((previous[previous_index], current[current_index]))

    removed = [
        item for index, item in enumerate(previous) if index not in matched_previous
    ]
    added = [item for index, item in enumerate(current) if index not in matched_current]
    return pairs, removed, added


def _format_time(value: datetime) -> str:
    return value.strftime("%d.%m %H:%M")


def compare_schedules(
    previous: list[NormalizedLesson],
    current: list[NormalizedLesson],
) -> list[LessonChange]:
    pairs, removed, added = pair_lessons(previous, current)
    changes: list[LessonChange] = []

    for before, after in pairs:
        if before.is_cancelled != after.is_cancelled:
            kind = ChangeKind.cancelled if after.is_cancelled else ChangeKind.restored
            message = (
                f"Занятие отменено: {after.subject}, {_format_time(after.starts_at)}"
                if after.is_cancelled
                else (
                    f"Занятие восстановлено: {after.subject}, "
                    f"{_format_time(after.starts_at)}"
                )
            )
            changes.append(LessonChange(kind, before, after, message))

        if before.starts_at != after.starts_at or before.ends_at != after.ends_at:
            changes.append(
                LessonChange(
                    ChangeKind.time_changed,
                    before,
                    after,
                    f"Изменено время: {after.subject}, "
                    f"{_format_time(before.starts_at)} → "
                    f"{_format_time(after.starts_at)}",
                )
            )

        if before.location_text != after.location_text:
            changes.append(
                LessonChange(
                    ChangeKind.location_changed,
                    before,
                    after,
                    f"Изменено место: {after.subject}, "
                    f"{before.location_text or 'не указано'} → "
                    f"{after.location_text or 'не указано'}",
                )
            )

        if _teacher_set(before) != _teacher_set(after):
            changes.append(
                LessonChange(
                    ChangeKind.teacher_changed,
                    before,
                    after,
                    f"Изменён преподаватель: {after.subject}",
                )
            )

        if before.delivery_mode != after.delivery_mode:
            changes.append(
                LessonChange(
                    ChangeKind.delivery_mode_changed,
                    before,
                    after,
                    f"Изменён формат занятия: {after.subject}, "
                    f"{before.delivery_mode.value} → {after.delivery_mode.value}",
                )
            )

    for lesson in removed:
        changes.append(
            LessonChange(
                ChangeKind.removed,
                lesson,
                None,
                f"Занятие удалено: {lesson.subject}, {_format_time(lesson.starts_at)}",
            )
        )

    for lesson in added:
        changes.append(
            LessonChange(
                ChangeKind.added,
                None,
                lesson,
                f"Добавлено занятие: {lesson.subject}, "
                f"{_format_time(lesson.starts_at)}",
            )
        )

    return sorted(
        changes,
        key=lambda change: (
            (change.after or change.before).starts_at,  # type: ignore[union-attr]
            change.kind.value,
        ),
    )
