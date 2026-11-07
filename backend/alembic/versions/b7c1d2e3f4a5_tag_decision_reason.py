"""tag application decision reason

Revision ID: b7c1d2e3f4a5
Revises: 7c1f2a9b4d6e
Create Date: 2026-10-30 10:55:00.000000

Business explanation for an administrator rejecting a tag application one by one.
Historical applications remain NULL; do not backfill or invent reasons.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: str | None = "7c1f2a9b4d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_tag_applications",
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_tag_applications", "decision_reason")
