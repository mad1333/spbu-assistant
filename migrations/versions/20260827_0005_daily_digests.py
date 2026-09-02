"""Add daily digest delivery state and editable message bindings.

Revision ID: 20260827_0005
Revises: 20260827_0004
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0005"
down_revision: str | None = "20260827_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_users",
        sa.Column("last_morning_digest_on", sa.Date(), nullable=True),
    )
    op.add_column(
        "telegram_users",
        sa.Column("last_evening_digest_on", sa.Date(), nullable=True),
    )
    op.create_table(
        "telegram_day_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "telegram_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "telegram_id",
            "target_date",
            "kind",
            name="uq_telegram_day_message",
        ),
    )
    op.create_index(
        "ix_telegram_day_messages_telegram_id",
        "telegram_day_messages",
        ["telegram_id"],
    )
    op.create_index(
        "ix_telegram_day_messages_target_date",
        "telegram_day_messages",
        ["target_date"],
    )


def downgrade() -> None:
    op.drop_table("telegram_day_messages")
    op.drop_column("telegram_users", "last_evening_digest_on")
    op.drop_column("telegram_users", "last_morning_digest_on")
