"""Moderated user avatars."""
import sqlalchemy as sa
from alembic import op

revision = 'e9a2b3c4d5f6'
down_revision = 'c8a1e2f3d4b5'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("avatar_key", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("avatar_pending_key", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("avatar_review_status", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("avatar_review_reason", sa.String(500), nullable=True))

def downgrade():
    op.drop_column("users", "avatar_review_reason")
    op.drop_column("users", "avatar_review_status")
    op.drop_column("users", "avatar_pending_key")
    op.drop_column("users", "avatar_key")
