"""durable realtime events, per-user counters, retention and idempotency

Revision ID: f3a4b5c6d7e8
Revises: d1e2f3a4b5c6
Create Date: 2026-11-06 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f3a4b5c6d7e8'
down_revision: str | None = 'd1e2f3a4b5c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'realtime_events',
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('recipient_user_id', sa.BigInteger(), nullable=False),
        sa.Column('user_seq', sa.BigInteger(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=True),
        sa.Column('entity_id', sa.String(length=64), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('payload', JSONType, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_owner', sa.String(length=96), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('event_id', name=op.f('pk_realtime_events')),
        sa.UniqueConstraint('recipient_user_id', 'user_seq', name='uq_realtime_events_recipient_seq'),
    )
    op.create_index('ix_realtime_events_recipient_seq', 'realtime_events', ['recipient_user_id', 'user_seq'], unique=False)
    op.create_index('ix_realtime_events_pending', 'realtime_events', ['delivered_at', 'next_retry_at'], unique=False)
    op.create_index('ix_realtime_events_created_at', 'realtime_events', ['created_at'], unique=False)
    op.create_index('ix_realtime_events_lease', 'realtime_events', ['lease_expires_at'], unique=False)
    op.create_index('ix_realtime_events_dead', 'realtime_events', ['dead_at'], unique=False)

    op.create_table(
        'user_event_counters',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('last_seq', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_event_counters')),
    )

    op.create_table(
        'realtime_retention',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('low_seq', sa.BigInteger(), server_default='1', nullable=False),
        sa.Column('high_seq', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('user_id', name=op.f('pk_realtime_retention')),
    )

    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('operation', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('response', JSONType, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_records')),
        sa.UniqueConstraint('user_id', 'operation', 'key', name='uq_idempotency_scope'),
    )
    op.create_index('ix_idempotency_expires_at', 'idempotency_records', ['expires_at'], unique=False)

    op.create_table(
        'service_heartbeats',
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('instance_id', sa.String(length=64), nullable=False),
        sa.Column('release_id', sa.String(length=128), server_default='', nullable=False),
        sa.Column('protocol_version', sa.Integer(), server_default='2', nullable=False),
        sa.Column('status', sa.String(length=16), server_default='starting', nullable=False),
        sa.Column('details', JSONType, nullable=False),
        sa.Column('pid', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('name', name=op.f('pk_service_heartbeats')),
    )
    op.create_index('ix_service_heartbeats_heartbeat_at', 'service_heartbeats', ['heartbeat_at'], unique=False)

    context = op.get_context()
    if context.dialect.name == 'postgresql':
        config = context.config
        assert config is not None
        role = config.attributes.get('migration_app_role')
        schema = config.attributes['migration_schema']
        if not role:
            raise RuntimeError('migration app role is required to grant realtime privileges')
        for table in ('realtime_events', 'user_event_counters', 'realtime_retention',
                      'idempotency_records', 'service_heartbeats'):
            op.execute(sa.text(f'REVOKE ALL ON "{schema}".{table} FROM PUBLIC'))
        op.execute(sa.text(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".realtime_events TO "{role}"'))
        op.execute(sa.text(
            f'GRANT SELECT, INSERT, UPDATE ON "{schema}".user_event_counters TO "{role}"'))
        op.execute(sa.text(
            f'GRANT SELECT, INSERT, UPDATE ON "{schema}".realtime_retention TO "{role}"'))
        op.execute(sa.text(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".idempotency_records TO "{role}"'))
        op.execute(sa.text(
            f'GRANT SELECT, INSERT, UPDATE ON "{schema}".service_heartbeats TO "{role}"'))
        op.execute(sa.text(
            f'GRANT USAGE, SELECT ON SEQUENCE "{schema}".idempotency_records_id_seq TO "{role}"'))
    # Audit remains append-only: this migration never grants UPDATE/DELETE on
    # audit_events and never rewrites its existing grants.


def downgrade() -> None:
    op.drop_index('ix_service_heartbeats_heartbeat_at', table_name='service_heartbeats')
    op.drop_table('service_heartbeats')
    op.drop_index('ix_idempotency_expires_at', table_name='idempotency_records')
    op.drop_table('idempotency_records')
    op.drop_table('realtime_retention')
    op.drop_table('user_event_counters')
    op.drop_index('ix_realtime_events_dead', table_name='realtime_events')
    op.drop_index('ix_realtime_events_lease', table_name='realtime_events')
    op.drop_index('ix_realtime_events_created_at', table_name='realtime_events')
    op.drop_index('ix_realtime_events_pending', table_name='realtime_events')
    op.drop_index('ix_realtime_events_recipient_seq', table_name='realtime_events')
    op.drop_table('realtime_events')
