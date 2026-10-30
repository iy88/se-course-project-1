"""direct upload leases"""
import sqlalchemy as sa

from alembic import op

revision = 'c8a1e2f3d4b5'
down_revision = 'b7c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('upload_leases',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('key', sa.String(512), nullable=False, unique=True),
        sa.Column('owner_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('namespace', sa.String(32), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.CheckConstraint("state IN ('pending','completed','failed')",name=op.f('ck_upload_leases_upload_state_allowed')),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760",name=op.f('ck_upload_leases_upload_size_allowed')),
        sa.CheckConstraint("length(sha256) = 64",name=op.f('ck_upload_leases_upload_sha256_length')))
    op.create_index('ix_upload_leases_owner_id', 'upload_leases', ['owner_id'])


def downgrade():
    op.drop_index('ix_upload_leases_owner_id', table_name='upload_leases')
    op.drop_table('upload_leases')
