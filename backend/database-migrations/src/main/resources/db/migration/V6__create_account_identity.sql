-- Account identity: accounts, persistent session guards, revocation intents and
-- email verification rounds (Q-001, Q-003).

CREATE OR REPLACE FUNCTION normalize_email(value TEXT) RETURNS TEXT
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
SELECT lower(btrim(value))
$$;

CREATE TABLE account (
    account_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL CHECK (btrim(email) <> ''),
    display_name TEXT NOT NULL CHECK (btrim(display_name) <> ''),
    password_hash TEXT NOT NULL CHECK (password_hash <> ''),
    credential_version INTEGER NOT NULL DEFAULT 1 CHECK (credential_version > 0),
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'manager')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp()
);

CREATE UNIQUE INDEX account_email_key ON account (normalize_email(email));

CREATE TABLE session_guard (
    session_id UUID PRIMARY KEY,
    token_digest BYTEA NOT NULL CHECK (octet_length(token_digest) = 32),
    account_id BIGINT NOT NULL REFERENCES account (account_id),
    credential_version INTEGER NOT NULL CHECK (credential_version > 0),
    issued_at TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    idle_timeout_seconds INTEGER NOT NULL CHECK (idle_timeout_seconds > 0),
    renew_interval_seconds INTEGER NOT NULL
        CHECK (renew_interval_seconds > 0 AND renew_interval_seconds < idle_timeout_seconds),
    csrf_digest BYTEA NOT NULL CHECK (octet_length(csrf_digest) = 32),
    revoked_at TIMESTAMPTZ,
    UNIQUE (token_digest),
    CHECK (issued_at < absolute_expires_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);

CREATE INDEX session_guard_account_idx ON session_guard (account_id, absolute_expires_at);
CREATE INDEX session_guard_expiry_idx ON session_guard (absolute_expires_at);

CREATE TABLE session_revocation (
    session_id UUID PRIMARY KEY REFERENCES session_guard (session_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    completed_at TIMESTAMPTZ,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);

CREATE INDEX session_revocation_pending_idx
    ON session_revocation (next_attempt_at, session_id)
    WHERE completed_at IS NULL;

CREATE TABLE email_verification (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purpose TEXT NOT NULL
        CHECK (purpose IN ('registration', 'password_reset', 'email_change_old', 'email_change_new')),
    email TEXT NOT NULL CHECK (btrim(email) <> ''),
    account_id BIGINT REFERENCES account (account_id),
    entry_digest BYTEA CHECK (entry_digest IS NULL OR octet_length(entry_digest) = 32),
    group_id UUID NOT NULL,
    credential_version INTEGER CHECK (credential_version IS NULL OR credential_version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    code TEXT,
    code_length INTEGER NOT NULL CHECK (code_length BETWEEN 6 AND 10),
    max_failed_attempts INTEGER NOT NULL CHECK (max_failed_attempts BETWEEN 1 AND 20),
    rule_version TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    consumed_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    delivery_rules JSONB NOT NULL CHECK (jsonb_typeof(delivery_rules) = 'object'),
    send_attempts INTEGER NOT NULL DEFAULT 0 CHECK (send_attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    last_delivery_error TEXT,
    UNIQUE (group_id, purpose),
    CHECK (expires_at > created_at),
    CHECK (code IS NULL OR char_length(code) = code_length),
    CHECK (num_nonnulls(consumed_at, invalidated_at) <= 1),
    CHECK (consumed_at IS NULL AND invalidated_at IS NULL OR code IS NULL),
    CHECK ((lease_token IS NULL) = (lease_until IS NULL)),
    CHECK ((purpose = 'registration') = (account_id IS NULL)),
    CHECK ((purpose IN ('registration', 'password_reset')) = (entry_digest IS NOT NULL)),
    CHECK ((purpose <> 'registration') = (credential_version IS NOT NULL))
);

CREATE INDEX email_verification_scope_idx
    ON email_verification (purpose, account_id, normalize_email(email));
CREATE INDEX email_verification_entry_idx
    ON email_verification (purpose, entry_digest, normalize_email(email));
CREATE INDEX email_verification_send_idx
    ON email_verification (next_attempt_at, id)
    WHERE sent_at IS NULL AND consumed_at IS NULL AND invalidated_at IS NULL;
CREATE INDEX email_verification_lease_idx
    ON email_verification (lease_until)
    WHERE lease_token IS NOT NULL;
