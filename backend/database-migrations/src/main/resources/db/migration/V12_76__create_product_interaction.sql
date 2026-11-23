-- Product comments, seller replies and account favourites (S2-04, issue #76).

CREATE TABLE product_comment (
    comment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    author_account_id BIGINT NOT NULL REFERENCES account (account_id),
    parent_comment_id BIGINT REFERENCES product_comment (comment_id),
    body TEXT NOT NULL CHECK (btrim(body) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    removed_at TIMESTAMPTZ,
    removed_by_admin_id BIGINT REFERENCES account (account_id),
    removed_reason TEXT,
    basis_ref TEXT,
    -- A comment can never be its own parent; replies stay one level deep in the use case.
    CHECK (parent_comment_id IS NULL OR parent_comment_id <> comment_id),
    CHECK ((removed_at IS NULL) = (removed_by_admin_id IS NULL)),
    CHECK ((removed_at IS NULL) = (removed_reason IS NULL)),
    CHECK ((removed_at IS NULL) = (basis_ref IS NULL))
);

-- Top-level comments page newest first; replies page oldest first under their parent.
CREATE INDEX product_comment_top_level_idx ON product_comment (product_id, created_at DESC, comment_id DESC)
    WHERE parent_comment_id IS NULL;
CREATE INDEX product_comment_reply_idx ON product_comment (parent_comment_id, created_at ASC, comment_id ASC)
    WHERE parent_comment_id IS NOT NULL;
CREATE INDEX product_comment_author_idx ON product_comment (author_account_id, created_at DESC);

CREATE TABLE product_favorite (
    favorite_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES account (account_id),
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (account_id, product_id)
);

CREATE INDEX product_favorite_account_idx ON product_favorite (account_id, created_at DESC, favorite_id DESC);
