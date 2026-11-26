-- Persistent email-verification send budget (S2 I-05).
--
-- The row key is a keyed digest of the normalized address, so a password-reset probe for an
-- unknown address does not retain the raw address. The primary key is the serialization point:
-- requests for the same purpose and address contend on this row before any verification row is
-- changed. V23_74 is deliberately a standalone migration; earlier version numbers stay untouched.

CREATE TABLE email_request_budget (
    purpose TEXT NOT NULL
        CHECK (purpose IN ('registration', 'password_reset', 'email_change')),
    email_digest BYTEA NOT NULL CHECK (octet_length(email_digest) = 32),
    last_requested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (purpose, email_digest)
);

CREATE INDEX email_request_budget_scan_idx
    ON email_request_budget (last_requested_at);
