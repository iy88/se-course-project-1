-- Account ban facts owned by the account module (S4-01, issue #81).
--
-- A restriction is identified by its case source. Different case sources may stack on one
-- account; only an active record for the same account and case is unique. Released rows stay in
-- place so the case adapter can still resolve the original record after a lift. case_id is not a
-- foreign key because the account module must not depend on the case module's schema.

CREATE TABLE account_ban (
    ban_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES account (account_id),
    case_id BIGINT NOT NULL CHECK (case_id > 0),
    applied_by BIGINT NOT NULL REFERENCES account (account_id),
    applied_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    basis_ref TEXT NOT NULL CHECK (btrim(basis_ref) <> ''),
    released_at TIMESTAMPTZ,
    released_by BIGINT REFERENCES account (account_id),
    release_reason TEXT CHECK (release_reason IS NULL OR btrim(release_reason) <> ''),
    release_basis_ref TEXT CHECK (release_basis_ref IS NULL OR btrim(release_basis_ref) <> ''),
    CHECK (released_at IS NULL OR released_at >= applied_at),
    CHECK (num_nonnulls(released_at, released_by, release_reason, release_basis_ref) IN (0, 4))
);

-- At most one effective record per account and case source; other sources remain independent.
CREATE UNIQUE INDEX account_ban_effective_source_key
    ON account_ban (account_id, case_id)
    WHERE released_at IS NULL;

-- Account qualification reads and the historical as-of predicate.
CREATE INDEX account_ban_account_idx
    ON account_ban (account_id, applied_at, released_at);

-- Resolve restrictions by their case source.
CREATE INDEX account_ban_case_idx ON account_ban (case_id);

-- Global as-of statistics over all account restrictions.
CREATE INDEX account_ban_applied_idx ON account_ban (applied_at);
