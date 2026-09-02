from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0009"
down_revision: str | None = "20260901_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_users", sa.Column("username", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "telegram_users",
        sa.Column("display_name", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "telegram_users",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_users",
        sa.Column(
            "interaction_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "telegram_users",
        sa.Column(
            "apple_calendar_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_users",
        sa.Column(
            "google_calendar_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_telegram_users_last_active_at",
        "telegram_users",
        ["last_active_at"],
    )
    op.alter_column("telegram_users", "interaction_count", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_telegram_users_last_active_at", table_name="telegram_users")
    op.drop_column("telegram_users", "google_calendar_requested_at")
    op.drop_column("telegram_users", "apple_calendar_requested_at")
    op.drop_column("telegram_users", "interaction_count")
    op.drop_column("telegram_users", "last_active_at")
    op.drop_column("telegram_users", "display_name")
    op.drop_column("telegram_users", "username")
