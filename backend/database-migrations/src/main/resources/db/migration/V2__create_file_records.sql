CREATE TABLE file_record (
    file_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_account_id BIGINT NOT NULL CHECK (owner_account_id > 0),
    purpose TEXT NOT NULL CHECK (purpose IN ('product_image', 'case_evidence')),
    state TEXT NOT NULL CHECK (state IN ('uploading', 'verified', 'cleaning', 'deleted')),
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    declared_size BIGINT NOT NULL CHECK (declared_size > 0),
    declared_content_type TEXT NOT NULL,
    target_type TEXT,
    target_id BIGINT CHECK (target_id > 0),
    upload_rule_version TEXT NOT NULL,
    upload_rules JSONB NOT NULL CHECK (jsonb_typeof(upload_rules) = 'object'),
    signing_credential_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    upload_expires_at TIMESTAMPTZ NOT NULL,
    cleanup_after TIMESTAMPTZ NOT NULL,
    verified_at TIMESTAMPTZ,
    content_etag TEXT,
    content_sha256 TEXT CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    verified_size BIGINT CHECK (verified_size > 0),
    verified_content_type TEXT,
    last_cleanup_at TIMESTAMPTZ,
    last_cleanup_request_id TEXT,
    CHECK ((target_type IS NULL) = (target_id IS NULL)),
    CHECK (created_at < upload_expires_at AND upload_expires_at < cleanup_after),
    CHECK (verified_at IS NULL OR (created_at <= verified_at AND verified_at < upload_expires_at)),
    CHECK (num_nonnulls(verified_at, content_etag, content_sha256, verified_size, verified_content_type) IN (0, 5)),
    CHECK (state <> 'verified' OR verified_at IS NOT NULL),
    CHECK (state <> 'uploading' OR verified_at IS NULL),
    CHECK (verified_size IS NULL OR verified_size = declared_size),
    CHECK (verified_content_type IS NULL OR verified_content_type = declared_content_type)
);

CREATE INDEX file_record_owner_purpose_idx ON file_record (owner_account_id, purpose, file_id);
CREATE INDEX file_record_cleanup_idx ON file_record (state, cleanup_after, file_id);

CREATE TABLE file_reference (
    reference_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES file_record (file_id),
    target_type TEXT NOT NULL,
    target_id BIGINT NOT NULL CHECK (target_id > 0),
    slot TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (file_id, target_type, target_id, slot)
);

CREATE INDEX file_reference_target_idx ON file_reference (target_type, target_id, reference_id);
