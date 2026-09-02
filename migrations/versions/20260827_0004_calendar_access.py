"""Add revocable calendar access generation.

Revision ID: 20260827_0004
Revises: 20260827_0003
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0004"
down_revision: str | None = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_users",
        sa.Column(
            "calendar_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("telegram_users", "calendar_generation")
