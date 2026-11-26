CREATE TABLE trade_purchase_product_snapshot (
    trade_id BIGINT PRIMARY KEY REFERENCES trade (id) ON DELETE CASCADE,
    content_version INTEGER NOT NULL CHECK (content_version > 0),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE product_case_snapshot (
    case_id BIGINT PRIMARY KEY REFERENCES moderation_case (id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL,
    content_version INTEGER NOT NULL CHECK (content_version > 0),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
    captured_at TIMESTAMPTZ NOT NULL
);
