from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time

from app.database.models import ActivityType, DeliveryMode, DisplayMode


@dataclass(frozen=True, slots=True)
class GroupOption:
    id: uuid.UUID
    source_id: int
    display_name: str
    direction: str | None = None


@dataclass(frozen=True, slots=True)
class UserContext:
    telegram_id: int
    current_group: GroupOption | None
    display_mode: DisplayMode
    show_teacher: bool
    show_location: bool
    show_delivery_mode: bool
    morning_digest_enabled: bool
    morning_digest_time: time
    evening_digest_enabled: bool
    evening_digest_time: time
    english_subgroup_key: str | None
    english_subgroup_label: str | None
    calendar_generation: int


@dataclass(frozen=True, slots=True)
class ScheduleLesson:
    lesson_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    subject: str
    activity_type: ActivityType
    delivery_mode: DeliveryMode
    location_text: str | None
    building_alias: str | None
    room: str | None
    teacher_names: tuple[str, ...]
    is_cancelled: bool
    observed_at: datetime
