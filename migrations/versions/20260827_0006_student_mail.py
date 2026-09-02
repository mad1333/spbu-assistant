"""Add encrypted student mail accounts and notification deduplication.

Revision ID: 20260827_0006
Revises: 20260827_0005
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0006"
down_revision: str | None = "20260827_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_users",
        sa.Column(
            "mail_setup_generation", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.create_table(
        "student_mail_accounts",
        sa.Column(
            "telegram_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.telegram_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("encrypted_app_password", sa.Text(), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("uid_validity", sa.String(length=64), nullable=True),
        sa.Column("last_seen_uid", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("last_error_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mail_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "telegram_id",
            sa.BigInteger(),
            sa.ForeignKey("student_mail_accounts.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uid_validity", sa.String(length=64), nullable=False),
        sa.Column("message_uid", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.String(length=998), nullable=True),
        sa.Column("sender", sa.String(length=998), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "telegram_id",
            "uid_validity",
            "message_uid",
            name="uq_mail_notification_uid",
        ),
    )
    op.create_index(
        "ix_mail_notifications_telegram_id",
        "mail_notifications",
        ["telegram_id"],
    )
    op.create_index(
        "ix_mail_notification_notified",
        "mail_notifications",
        ["notified_at"],
    )


def downgrade() -> None:
    op.drop_table("mail_notifications")
    op.drop_table("student_mail_accounts")
    op.drop_column("telegram_users", "mail_setup_generation")
