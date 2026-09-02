"""Expand group direction for the official AMCP catalogue.

Revision ID: 20260831_0007
Revises: 20260827_0006
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0007"
down_revision: str | None = "20260827_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "student_groups",
        "direction",
        existing_type=sa.String(length=128),
        type_=sa.String(length=256),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "student_groups",
        "direction",
        existing_type=sa.String(length=256),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
