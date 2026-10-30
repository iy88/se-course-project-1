"""Attach avatar review to shared cases."""
import sqlalchemy as sa
from alembic import op

revision = 'f1a2b3c4d5e6'
down_revision = 'e9a2b3c4d5f6'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('disposal_cases', sa.Column('avatar_key', sa.String(512), nullable=True))
    op.execute(sa.text("INSERT INTO disposal_cases (case_type, status, subject_user_id, title, avatar_key) SELECT 'avatar_review', 'pending', id, '头像审核', avatar_pending_key FROM users WHERE avatar_review_status='pending' AND avatar_pending_key IS NOT NULL"))

def downgrade():
    op.drop_column('disposal_cases', 'avatar_key')
