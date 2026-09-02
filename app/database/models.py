from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class LessonStatus(StrEnum):
    active = "active"
    cancelled = "cancelled"
    removed = "removed"


class ActivityType(StrEnum):
    lecture = "lecture"
    practical = "practical"
    seminar = "seminar"
    laboratory = "laboratory"
    consultation = "consultation"
    assessment = "assessment"
    other = "other"


class DeliveryMode(StrEnum):
    offline = "offline"
    online = "online"
    hybrid = "hybrid"
    unknown = "unknown"


class ChangeKind(StrEnum):
    added = "added"
    removed = "removed"
    cancelled = "cancelled"
    restored = "restored"
    time_changed = "time_changed"
    location_changed = "location_changed"
    teacher_changed = "teacher_changed"
    delivery_mode_changed = "delivery_mode_changed"


class DisplayMode(StrEnum):
    compact = "compact"
    normal = "normal"
    detailed = "detailed"


class StudentGroup(Base):
    __tablename__ = "student_groups"
    __table_args__ = (UniqueConstraint("source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    direction: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    snapshots: Mapped[list[ScheduleSnapshot]] = relationship(back_populates="group")
    lessons: Mapped[list[Lesson]] = relationship(back_populates="group")
    telegram_users: Mapped[list[TelegramUser]] = relationship(
        back_populates="current_group"
    )


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    current_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    display_mode: Mapped[DisplayMode] = mapped_column(
        Enum(DisplayMode, name="display_mode"), default=DisplayMode.normal
    )
    show_teacher: Mapped[bool] = mapped_column(Boolean, default=True)
    show_location: Mapped[bool] = mapped_column(Boolean, default=True)
    show_delivery_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    morning_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    morning_digest_time: Mapped[time] = mapped_column(Time, default=time(7, 30))
    evening_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    evening_digest_time: Mapped[time] = mapped_column(Time, default=time(20, 0))
    english_subgroup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    english_subgroup_label: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    calendar_generation: Mapped[int] = mapped_column(Integer, default=0)
    mail_setup_generation: Mapped[int] = mapped_column(Integer, default=0)
    last_morning_digest_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_evening_digest_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    current_group: Mapped[StudentGroup | None] = relationship(
        back_populates="telegram_users"
    )
    mail_account: Mapped[StudentMailAccount | None] = relationship(
        back_populates="telegram_user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TelegramDayMessage(Base):
    __tablename__ = "telegram_day_messages"
    __table_args__ = (
        UniqueConstraint(
            "telegram_id",
            "target_date",
            "kind",
            name="uq_telegram_day_message",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("telegram_users.telegram_id", ondelete="CASCADE"),
        index=True,
    )
    target_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudentMailAccount(Base):
    __tablename__ = "student_mail_accounts"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("telegram_users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
    )
    address: Mapped[str] = mapped_column(String(320))
    encrypted_app_password: Mapped[str] = mapped_column(Text)
    imap_host: Mapped[str] = mapped_column(String(255), default="imap.mail.ru")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    uid_validity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_uid: Mapped[int] = mapped_column(BigInteger, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    telegram_user: Mapped[TelegramUser] = relationship(back_populates="mail_account")


class MailNotification(Base):
    __tablename__ = "mail_notifications"
    __table_args__ = (
        UniqueConstraint(
            "telegram_id",
            "uid_validity",
            "message_uid",
            name="uq_mail_notification_uid",
        ),
        Index("ix_mail_notification_notified", "notified_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("student_mail_accounts.telegram_id", ondelete="CASCADE"),
        index=True,
    )
    uid_validity: Mapped[str] = mapped_column(String(64))
    message_uid: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    sender: Mapped[str] = mapped_column(String(998))
    subject: Mapped[str] = mapped_column(String(998))
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Teacher(Base):
    __tablename__ = "teachers"
    __table_args__ = (UniqueConstraint("source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    short_name: Mapped[str] = mapped_column(String(256), index=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_address: Mapped[str] = mapped_column(String(512), unique=True)
    short_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    official_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latitude: Mapped[str | None] = mapped_column(String(32), nullable=True)
    longitude: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ScheduleSnapshot(Base):
    __tablename__ = "schedule_snapshots"
    __table_args__ = (Index("ix_snapshot_group_fetched", "group_id", "fetched_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_groups.id", ondelete="CASCADE")
    )
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    group: Mapped[StudentGroup] = relationship(back_populates="snapshots")
    revisions: Mapped[list[LessonRevision]] = relationship(back_populates="snapshot")


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (Index("ix_lesson_group_status", "group_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_groups.id", ondelete="CASCADE")
    )
    status: Mapped[LessonStatus] = mapped_column(
        Enum(LessonStatus, name="lesson_status"), default=LessonStatus.active
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    group: Mapped[StudentGroup] = relationship(back_populates="lessons")
    revisions: Mapped[list[LessonRevision]] = relationship(
        back_populates="lesson", order_by="LessonRevision.observed_at"
    )


class LessonRevision(Base):
    __tablename__ = "lesson_revisions"
    __table_args__ = (
        UniqueConstraint("lesson_id", "snapshot_id", name="uq_lesson_snapshot"),
        Index("ix_revision_start", "starts_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE")
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schedule_snapshots.id", ondelete="CASCADE")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str] = mapped_column(String(512))
    subject_normalized: Mapped[str] = mapped_column(String(512), index=True)
    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, name="activity_type")
    )
    delivery_mode: Mapped[DeliveryMode] = mapped_column(
        Enum(DeliveryMode, name="delivery_mode")
    )
    location_text: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    building_alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room: Mapped[str | None] = mapped_column(String(128), nullable=True)
    teacher_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    source_marked_time_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_marked_location_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_marked_teacher_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON)

    lesson: Mapped[Lesson] = relationship(back_populates="revisions")
    snapshot: Mapped[ScheduleSnapshot] = relationship(back_populates="revisions")


class DetectedChange(Base):
    __tablename__ = "detected_changes"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_change_deduplication_key"),
        Index("ix_change_detected", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE")
    )
    kind: Mapped[ChangeKind] = mapped_column(Enum(ChangeKind, name="change_kind"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deduplication_key: Mapped[str] = mapped_column(String(64))
    before_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(Text)
