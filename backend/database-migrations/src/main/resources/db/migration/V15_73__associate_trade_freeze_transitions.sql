-- A trade freeze transition is identified by its trade_state_history row. The nullable association keeps
-- legacy history valid and lets case-owned release resolve exactly the freeze that a transition changed.
ALTER TABLE trade_state_history
    ADD COLUMN freeze_id BIGINT REFERENCES trade_freeze (id),
    ADD COLUMN from_frozen BOOLEAN,
    ADD COLUMN to_frozen BOOLEAN;

ALTER TABLE trade_state_history ADD CONSTRAINT trade_state_history_freeze_state_chk
    CHECK ((freeze_id IS NULL) = (from_frozen IS NULL)
        AND (freeze_id IS NULL) = (to_frozen IS NULL));

CREATE UNIQUE INDEX trade_state_history_freeze_action_idx
    ON trade_state_history (freeze_id, action) WHERE freeze_id IS NOT NULL;
