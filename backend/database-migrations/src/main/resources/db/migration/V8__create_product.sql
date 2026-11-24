-- Products, category links, edit history, review audits and category applications.

CREATE SEQUENCE product_review_case_seq;

CREATE TABLE product (
    product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seller_account_id BIGINT NOT NULL REFERENCES account (account_id),
    title TEXT NOT NULL CHECK (btrim(title) <> ''),
    description TEXT NOT NULL,
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN
        ('pending_review', 'review_rejected', 'public', 'in_trade', 'off_shelf')),
    occupied_by_trade_id BIGINT UNIQUE CHECK (occupied_by_trade_id IS NULL OR occupied_by_trade_id > 0),
    content_version INTEGER NOT NULL DEFAULT 1 CHECK (content_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CHECK (updated_at >= created_at),
    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE INDEX product_public_idx ON product (created_at DESC, product_id DESC)
    WHERE lifecycle_state = 'public' AND deleted_at IS NULL;
CREATE INDEX product_seller_idx ON product (seller_account_id, product_id);

CREATE TABLE product_category (
    product_category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    category_id BIGINT NOT NULL REFERENCES category (category_id),
    source TEXT NOT NULL CHECK (source IN ('seller', 'application', 'admin_correction')),
    created_by_kind TEXT NOT NULL CHECK (created_by_kind IN ('seller', 'admin')),
    created_by_id BIGINT NOT NULL CHECK (created_by_id > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    removed_at TIMESTAMPTZ,
    removed_by_kind TEXT CHECK (removed_by_kind IS NULL OR removed_by_kind IN ('seller', 'admin')),
    removed_by_id BIGINT CHECK (removed_by_id IS NULL OR removed_by_id > 0),
    change_basis_type TEXT,
    change_basis_id BIGINT CHECK (change_basis_id IS NULL OR change_basis_id > 0),
    CHECK ((removed_at IS NULL) = (removed_by_kind IS NULL)),
    CHECK ((removed_at IS NULL) = (removed_by_id IS NULL)),
    CHECK ((change_basis_type IS NULL) = (change_basis_id IS NULL))
);

CREATE UNIQUE INDEX product_category_active_key ON product_category (product_id, category_id)
    WHERE removed_at IS NULL;
CREATE INDEX product_category_category_idx ON product_category (category_id, product_id)
    WHERE removed_at IS NULL;

CREATE TABLE product_edit_history (
    edit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    operator_kind TEXT NOT NULL CHECK (operator_kind IN ('seller', 'admin')),
    operator_account_id BIGINT NOT NULL REFERENCES account (account_id),
    edit_kind TEXT NOT NULL CHECK (edit_kind IN ('content_edit', 'category_correction')),
    before_content JSONB NOT NULL CHECK (jsonb_typeof(before_content) = 'object'),
    after_content JSONB NOT NULL CHECK (jsonb_typeof(after_content) = 'object'),
    reason TEXT,
    basis_type TEXT,
    basis_id BIGINT CHECK (basis_id IS NULL OR basis_id > 0),
    edited_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    CHECK ((basis_type IS NULL) = (basis_id IS NULL))
);

CREATE INDEX product_edit_history_product_idx ON product_edit_history (product_id, edited_at DESC, edit_id DESC);

CREATE TABLE product_audit (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    case_id BIGINT NOT NULL UNIQUE DEFAULT nextval('product_review_case_seq'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'passed', 'rejected', 'withdrawn')),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    decided_by_admin_id BIGINT REFERENCES account (account_id),
    decided_at TIMESTAMPTZ,
    decision_reason TEXT,
    reviewed_content JSONB CHECK (reviewed_content IS NULL OR jsonb_typeof(reviewed_content) = 'object'),
    reviewed_application JSONB CHECK (reviewed_application IS NULL OR jsonb_typeof(reviewed_application) = 'object'),
    reviewed_banned_item_ids JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reviewed_banned_item_ids) = 'array'),
    withdrawn_at TIMESTAMPTZ,
    UNIQUE (product_id, sequence_no),
    CHECK ((decided_at IS NULL) = (decided_by_admin_id IS NULL)),
    CHECK (status <> 'pending' OR decided_at IS NULL),
    CHECK (status <> 'withdrawn' OR withdrawn_at IS NOT NULL)
);

CREATE UNIQUE INDEX product_audit_pending_key ON product_audit (product_id)
    WHERE status = 'pending';

CREATE TABLE category_application (
    application_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    submitted_by_account_id BIGINT NOT NULL REFERENCES account (account_id),
    proposed_name TEXT NOT NULL CHECK (btrim(proposed_name) <> ''),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    resolution TEXT CHECK (resolution IS NULL OR resolution IN ('new_category', 'existing_category')),
    resolved_category_id BIGINT REFERENCES category (category_id),
    decided_by_admin_id BIGINT REFERENCES account (account_id),
    decided_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    CHECK ((decided_at IS NULL) = (decided_by_admin_id IS NULL))
);

CREATE UNIQUE INDEX category_application_pending_key ON category_application (product_id)
    WHERE status = 'pending';
