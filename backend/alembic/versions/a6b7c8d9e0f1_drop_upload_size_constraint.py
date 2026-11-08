"""Move upload size policy out of the database constraint."""
from alembic import op
import sqlalchemy as sa

revision = 'a6b7c8d9e0f1'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('upload_leases') as batch:
        batch.drop_constraint(op.f('ck_upload_leases_upload_size_allowed'), type_='check')


def downgrade():
    count = op.get_bind().scalar(sa.text(
        'SELECT count(*) FROM upload_leases WHERE size_bytes <= 0 OR size_bytes > 10485760'
    ))
    if count:
        raise RuntimeError('Upload leases incompatible with the old size constraint exist; downgrade refused')
    with op.batch_alter_table('upload_leases') as batch:
        batch.create_check_constraint(op.f('ck_upload_leases_upload_size_allowed'),
                                      'size_bytes > 0 AND size_bytes <= 10485760')
