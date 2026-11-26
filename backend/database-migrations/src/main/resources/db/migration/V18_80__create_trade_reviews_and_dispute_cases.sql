-- Completed-trade reviews. Account identifiers stay without cross-domain foreign keys;
-- the trade row is authoritative and the application binds the reviewer/reviewee pair.

CREATE TABLE trade_review (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    reviewer_id BIGINT NOT NULL CHECK (reviewer_id > 0),
    reviewee_id BIGINT NOT NULL CHECK (reviewee_id > 0),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content VARCHAR(2000) NOT NULL CHECK (btrim(content) <> ''),
    visible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (trade_id, reviewer_id),
    CHECK (reviewer_id <> reviewee_id)
);

CREATE INDEX trade_review_reviewer_time_idx
    ON trade_review (reviewer_id, created_at DESC, id DESC);
CREATE INDEX trade_review_reviewee_time_idx
    ON trade_review (reviewee_id, created_at DESC, id DESC);
CREATE INDEX trade_review_trade_idx ON trade_review (trade_id, id);

-- Dispute cases reuse moderation_case for the shared case workbench. The link keeps the
-- private statement in trade_dispute and does not copy it into moderation_case.

CREATE TABLE trade_dispute_case (
    case_id BIGINT PRIMARY KEY REFERENCES moderation_case (id),
    dispute_id BIGINT NOT NULL UNIQUE,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    FOREIGN KEY (dispute_id, trade_id) REFERENCES trade_dispute (id, trade_id)
);

CREATE INDEX trade_dispute_case_trade_idx ON trade_dispute_case (trade_id, case_id);
