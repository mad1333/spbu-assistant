"""Store incoming mail bodies until Telegram delivery.

Revision ID: 20260901_0008
Revises: 20260831_0007
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0008"
down_revision: str | None = "20260831_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mail_notifications", sa.Column("body_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "mail_notifications",
        sa.Column(
            "body_truncated", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("mail_notifications", "body_truncated")
    op.drop_column("mail_notifications", "body_text")
