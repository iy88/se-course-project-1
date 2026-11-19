CREATE TABLE operation_record (
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    digest_version TEXT NOT NULL,
    request_digest BYTEA NOT NULL,
    operation_id UUID NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    response_status INTEGER,
    response_data JSONB,
    resource_type TEXT,
    resource_id BIGINT,
    PRIMARY KEY (actor_kind, actor_id, operation_name, idempotency_key),
    CHECK ((response_status IS NULL) = (response_data IS NULL)),
    CHECK ((resource_type IS NULL) = (resource_id IS NULL)),
    CHECK (resource_id IS NULL OR resource_id > 0)
);
CREATE INDEX operation_record_expiry_idx ON operation_record (expires_at);

CREATE TABLE audit_record (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    request_id UUID NOT NULL,
    operation_id UUID NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id BIGINT NOT NULL CHECK (target_id > 0),
    basis_type TEXT,
    basis_id BIGINT,
    facts JSONB NOT NULL CHECK (jsonb_typeof(facts) = 'object'),
    config_version TEXT NOT NULL,
    CHECK ((basis_type IS NULL) = (basis_id IS NULL)),
    CHECK (basis_id IS NULL OR basis_id > 0)
);
CREATE INDEX audit_record_operation_idx ON audit_record (operation_id);
