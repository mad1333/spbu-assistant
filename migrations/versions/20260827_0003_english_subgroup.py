"""Add English subgroup preference.

Revision ID: 20260827_0003
Revises: 20260827_0002
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0003"
down_revision: str | None = "20260827_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_users",
        sa.Column("english_subgroup_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "telegram_users",
        sa.Column("english_subgroup_label", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_users", "english_subgroup_label")
    op.drop_column("telegram_users", "english_subgroup_key")
