"""Initial timetable storage.

Revision ID: 20260827_0001
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

lesson_status = postgresql.ENUM(
    "active", "cancelled", "removed", name="lesson_status", create_type=False
)
activity_type = postgresql.ENUM(
    "lecture",
    "practical",
    "seminar",
    "laboratory",
    "consultation",
    "assessment",
    "other",
    name="activity_type",
    create_type=False,
)
delivery_mode = postgresql.ENUM(
    "offline",
    "online",
    "hybrid",
    "unknown",
    name="delivery_mode",
    create_type=False,
)
change_kind = postgresql.ENUM(
    "added",
    "removed",
    "cancelled",
    "restored",
    "time_changed",
    "location_changed",
    "teacher_changed",
    "delivery_mode_changed",
    name="change_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    lesson_status.create(bind, checkfirst=True)
    activity_type.create(bind, checkfirst=True)
    delivery_mode.create(bind, checkfirst=True)
    change_kind.create(bind, checkfirst=True)

    op.create_table(
        "student_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("direction", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index("ix_student_groups_source_id", "student_groups", ["source_id"])

    op.create_table(
        "teachers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("short_name", sa.String(length=256), nullable=False),
        sa.Column("full_name", sa.String(length=256), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index("ix_teachers_short_name", "teachers", ["short_name"])
    op.create_index("ix_teachers_source_id", "teachers", ["source_id"])

    op.create_table(
        "buildings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_address", sa.String(length=512), nullable=False, unique=True),
        sa.Column("short_name", sa.String(length=128), nullable=True),
        sa.Column("official_name", sa.String(length=512), nullable=True),
        sa.Column("latitude", sa.String(length=32), nullable=True),
        sa.Column("longitude", sa.String(length=32), nullable=True),
        sa.Column("verification_url", sa.String(length=1024), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    buildings = sa.table(
        "buildings",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("source_address", sa.String()),
        sa.column("short_name", sa.String()),
        sa.column("official_name", sa.String()),
        sa.column("verification_url", sa.String()),
        sa.column("verified_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        buildings,
        [
            {
                "id": UUID("8ce35c54-211c-4f77-b8f0-2d5bc0fdd628"),
                "source_address": "Санкт-Петербург, Университетский проспект, д. 28",
                "short_name": "МАТМЕХ",
                "official_name": "Математико-механический факультет СПбГУ",
                "verification_url": "https://se.math.spbu.ru/contacts.html",
                "verified_at": datetime.fromisoformat("2026-08-27T00:00:00+03:00"),
            },
            {
                "id": UUID("60dceeed-9c17-4c9b-925d-c15f5c894b38"),
                "source_address": "Санкт-Петербург, Университетский проспект, д. 35",
                "short_name": "ПМ-ПУ",
                "official_name": (
                    "Факультет прикладной математики — процессов управления СПбГУ"
                ),
                "verification_url": (
                    "https://pureportal.spbu.ru/ru/projects/"
                    "lviii----------control-processes-and-stability-cps27"
                    "%28c31a3a6b-65c5-4a33-90f6-5d841be11841%29.html"
                ),
                "verified_at": datetime.fromisoformat("2026-08-27T00:00:00+03:00"),
            },
        ],
    )

    op.create_table(
        "schedule_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_snapshot_group_fetched", "schedule_snapshots", ["group_id", "fetched_at"]
    )
    op.create_index(
        "ix_schedule_snapshots_fetched_at", "schedule_snapshots", ["fetched_at"]
    )
    op.create_index(
        "ix_schedule_snapshots_source_hash", "schedule_snapshots", ["source_hash"]
    )

    op.create_table(
        "lessons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", lesson_status, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lesson_group_status", "lessons", ["group_id", "status"])

    op.create_table(
        "lesson_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("subject_normalized", sa.String(length=512), nullable=False),
        sa.Column("activity_type", activity_type, nullable=False),
        sa.Column("delivery_mode", delivery_mode, nullable=False),
        sa.Column("location_text", sa.String(length=1024), nullable=True),
        sa.Column("building_alias", sa.String(length=128), nullable=True),
        sa.Column("room", sa.String(length=128), nullable=True),
        sa.Column("teacher_names", sa.JSON(), nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("source_marked_time_changed", sa.Boolean(), nullable=False),
        sa.Column("source_marked_location_changed", sa.Boolean(), nullable=False),
        sa.Column("source_marked_teacher_changed", sa.Boolean(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("lesson_id", "snapshot_id", name="uq_lesson_snapshot"),
    )
    op.create_index("ix_revision_start", "lesson_revisions", ["starts_at"])
    op.create_index(
        "ix_lesson_revisions_subject_normalized",
        "lesson_revisions",
        ["subject_normalized"],
    )

    op.create_table(
        "detected_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lesson_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", change_kind, nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("before_payload", sa.JSON(), nullable=True),
        sa.Column("after_payload", sa.JSON(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.UniqueConstraint("deduplication_key", name="uq_change_deduplication_key"),
    )
    op.create_index("ix_change_detected", "detected_changes", ["detected_at"])


def downgrade() -> None:
    op.drop_table("detected_changes")
    op.drop_table("lesson_revisions")
    op.drop_table("lessons")
    op.drop_table("schedule_snapshots")
    op.drop_table("buildings")
    op.drop_table("teachers")
    op.drop_table("student_groups")

    bind = op.get_bind()
    change_kind.drop(bind, checkfirst=True)
    delivery_mode.drop(bind, checkfirst=True)
    activity_type.drop(bind, checkfirst=True)
    lesson_status.drop(bind, checkfirst=True)
