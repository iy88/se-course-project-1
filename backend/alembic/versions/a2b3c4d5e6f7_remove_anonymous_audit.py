"""Remove historical anonymous audit events; retain explicit system tasks."""
import sqlalchemy as sa
from alembic import op

revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("DELETE FROM audit_events WHERE actor_role='anonymous' OR (actor_id IS NULL AND actor_role<>'system')"))


def downgrade():
    # Historical anonymous events cannot be reconstructed.
    pass
