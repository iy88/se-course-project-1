-- Test-only product, category, account and session fixtures. The review case and notification
-- tables are the real tables created by Flyway; these fixtures never ship with the application.
CREATE TABLE review_seller_fixture (
    account_id BIGINT PRIMARY KEY,
    display_name TEXT NOT NULL
);

CREATE TABLE review_session_fixture (
    session_id UUID PRIMARY KEY,
    account_id BIGINT NOT NULL,
    credential_version BIGINT NOT NULL
);

CREATE TABLE review_manager_fixture (
    account_id BIGINT PRIMARY KEY
);

CREATE TABLE review_product_fixture (
    product_id BIGINT PRIMARY KEY,
    seller_account_id BIGINT NOT NULL REFERENCES review_seller_fixture (account_id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
    content_version INTEGER NOT NULL CHECK (content_version > 0),
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('pending_review', 'review_rejected', 'public', 'off_shelf'))
);

CREATE TABLE review_product_image_fixture (
    product_id BIGINT NOT NULL REFERENCES review_product_fixture (product_id),
    file_id BIGINT NOT NULL,
    PRIMARY KEY (product_id, file_id)
);

CREATE TABLE review_category_fixture (
    category_id BIGINT PRIMARY KEY,
    main_name TEXT NOT NULL,
    selectable BOOLEAN NOT NULL
);

CREATE TABLE review_product_category_fixture (
    product_id BIGINT NOT NULL REFERENCES review_product_fixture (product_id),
    category_id BIGINT NOT NULL REFERENCES review_category_fixture (category_id),
    PRIMARY KEY (product_id, category_id)
);

CREATE TABLE review_audit_fixture (
    audit_id BIGINT PRIMARY KEY,
    case_id BIGINT NOT NULL UNIQUE,
    product_id BIGINT NOT NULL REFERENCES review_product_fixture (product_id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'passed', 'rejected', 'withdrawn')),
    submitted_at TIMESTAMPTZ NOT NULL,
    reviewed_content_version INTEGER,
    decision TEXT,
    reason TEXT,
    decided_at TIMESTAMPTZ,
    decided_by BIGINT
);

CREATE INDEX review_audit_case_idx ON review_audit_fixture (case_id);

CREATE TABLE review_category_application_fixture (
    application_id BIGINT PRIMARY KEY,
    audit_id BIGINT NOT NULL UNIQUE REFERENCES review_audit_fixture (audit_id),
    proposed_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    reason TEXT
);

CREATE TABLE review_banned_item_fixture (
    item_id BIGINT PRIMARY KEY,
    group_name TEXT NOT NULL,
    content TEXT NOT NULL,
    active BOOLEAN NOT NULL
);

-- Test projection of the product owner's public visibility rule.
CREATE VIEW review_public_products AS
    SELECT product_id FROM review_product_fixture WHERE lifecycle_state = 'public';
