"""Human text storage must not reject valid multi-codepoint grapheme clusters.

SQLite VARCHAR already has TEXT affinity and no enforced character length.
Downgrades refuse overlength data rather than silently truncating it.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None

COLUMNS = [['users', 'display_name', 64], ['users', 'avatar_review_reason', 500], ['account_restrictions', 'reason', 500], ['account_restrictions', 'basis', 500], ['account_restrictions', 'lift_reason', 500], ['categories', 'name', 64], ['category_aliases', 'name', 64], ['products', 'title', 120], ['products', 'display_restricted_reason', 500], ['products', 'reject_reason', 500], ['product_tag_applications', 'requested_name', 64], ['product_tag_applications', 'decision_reason', 500], ['product_edit_histories', 'reason', 500], ['review_records', 'reason', 500], ['comments', 'delete_reason', 500], ['prohibited_items', 'group_name', 64], ['prohibited_items', 'content', 500], ['trades', 'request_note', 500], ['trades', 'close_reason', 200], ['trades', 'frozen_reason', 500], ['trade_agreements', 'delivery_time', 200], ['trade_agreements', 'delivery_location', 200], ['trade_agreements', 'delivery_method', 200], ['trade_agreements', 'payment_method', 100], ['trade_agreements', 'payment_timing', 200], ['trade_transitions', 'reason', 500], ['completion_confirmations', 'note', 500], ['trade_reviews', 'delete_reason', 500], ['reports', 'reason', 500], ['reports', 'public_result', 500], ['reports', 'result_reason', 500], ['disposal_cases', 'title', 200], ['disposal_cases', 'conclusion', 200], ['disposal_cases', 'conclusion_reason', 500], ['disposal_cases', 'basis', 500], ['notifications', 'title', 200], ['notifications', 'content', 500]]


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        return
    for table, column, old_length in COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(old_length), type_=sa.Text())


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == 'sqlite':
        return
    # Preflight every column before any DDL; never shorten stored text on rollback.
    for table, column, old_length in COLUMNS:
        target = sa.table(table, sa.column(column))
        count = connection.scalar(sa.select(sa.func.count()).select_from(target).where(sa.func.length(target.c[column]) > old_length))
        if count:
            raise RuntimeError(f'{table}.{column} contains text incompatible with the old length; downgrade refused')
    for table, column, old_length in reversed(COLUMNS):
        op.alter_column(table, column, existing_type=sa.Text(), type_=sa.String(old_length))
