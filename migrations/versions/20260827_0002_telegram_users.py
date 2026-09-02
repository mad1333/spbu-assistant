"""Add Telegram users and personal schedule settings.

Revision ID: 20260827_0002
Revises: 20260827_0001
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0002"
down_revision: str | None = "20260827_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

display_mode = postgresql.ENUM(
    "compact",
    "normal",
    "detailed",
    name="display_mode",
    create_type=False,
)


def upgrade() -> None:
    display_mode.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "telegram_users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "current_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "display_mode",
            display_mode,
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "show_teacher", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "show_location", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "show_delivery_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "morning_digest_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "morning_digest_time",
            sa.Time(),
            nullable=False,
            server_default="07:30:00",
        ),
        sa.Column(
            "evening_digest_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "evening_digest_time",
            sa.Time(),
            nullable=False,
            server_default="20:00:00",
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Europe/Moscow",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_telegram_users_current_group_id",
        "telegram_users",
        ["current_group_id"],
    )


def downgrade() -> None:
    op.drop_table("telegram_users")
    display_mode.drop(op.get_bind(), checkfirst=True)
