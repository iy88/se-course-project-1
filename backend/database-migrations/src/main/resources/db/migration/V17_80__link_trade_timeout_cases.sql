CREATE TABLE trade_timeout_case (
    case_id BIGINT PRIMARY KEY REFERENCES moderation_case (id),
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    reason TEXT NOT NULL CHECK (btrim(reason) <> '')
);

CREATE INDEX trade_timeout_case_trade_idx ON trade_timeout_case (trade_id);
