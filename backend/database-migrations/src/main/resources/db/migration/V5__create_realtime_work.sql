CREATE TABLE event_namespace (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    epoch UUID NOT NULL
);
INSERT INTO event_namespace VALUES (true, gen_random_uuid());

CREATE TABLE account_event_head (
    account_id BIGINT PRIMARY KEY CHECK (account_id > 0),
    seq_head BIGINT NOT NULL DEFAULT 0 CHECK (seq_head BETWEEN 0 AND 9007199254740991),
    replay_floor BIGINT NOT NULL DEFAULT 0 CHECK (replay_floor BETWEEN 0 AND seq_head)
);

CREATE TABLE user_event (
    event_id UUID PRIMARY KEY,
    recipient_account_id BIGINT NOT NULL REFERENCES account_event_head (account_id),
    account_seq BIGINT NOT NULL CHECK (account_seq BETWEEN 1 AND 9007199254740991),
    event_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    intent_key TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id BIGINT NOT NULL CHECK (source_id > 0),
    payload_type TEXT,
    payload_id BIGINT CHECK (payload_id > 0),
    source_sequence BIGINT CHECK (source_sequence BETWEEN 0 AND 9007199254740991),
    origin_connection_id UUID,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    UNIQUE (recipient_account_id, account_seq),
    UNIQUE (recipient_account_id, intent_key),
    CHECK ((payload_type IS NULL) = (payload_id IS NULL)),
    CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);
CREATE INDEX user_event_dispatch_idx ON user_event (next_attempt_at, event_id) WHERE published_at IS NULL;
CREATE INDEX user_event_expiry_idx ON user_event (expires_at, recipient_account_id);

CREATE TABLE task_schedule (
    task_id UUID PRIMARY KEY,
    task_kind TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id BIGINT NOT NULL CHECK (source_id > 0),
    trigger_key TEXT NOT NULL,
    source_version TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    rule_version TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    last_error TEXT,
    UNIQUE (task_kind, trigger_key),
    CHECK ((lease_token IS NULL) = (lease_until IS NULL)),
    CHECK (num_nonnulls(completed_at, cancelled_at) <= 1)
);
CREATE INDEX task_schedule_due_idx ON task_schedule (next_attempt_at, task_id)
WHERE completed_at IS NULL AND cancelled_at IS NULL;
