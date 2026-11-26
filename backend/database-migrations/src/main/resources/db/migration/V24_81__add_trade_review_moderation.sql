-- Review moderation keeps the original body and rating. Legacy rows with visible = false stay
-- hidden; a moderation record now adds the executor, reason, basis and time together.

ALTER TABLE trade_review
    ADD COLUMN removed_at TIMESTAMPTZ,
    ADD COLUMN removed_by BIGINT,
    ADD COLUMN removed_reason TEXT,
    ADD COLUMN removal_basis_ref TEXT;

ALTER TABLE trade_review
    ADD CONSTRAINT trade_review_moderation_together CHECK (
        (removed_at IS NULL) = (removed_by IS NULL)
        AND (removed_at IS NULL) = (removed_reason IS NULL)
        AND (removed_at IS NULL) = (removal_basis_ref IS NULL)
    ),
    ADD CONSTRAINT trade_review_removed_is_hidden CHECK (
        removed_at IS NULL OR visible = FALSE
    ),
    ADD CONSTRAINT trade_review_removed_by_positive CHECK (removed_by IS NULL OR removed_by > 0),
    ADD CONSTRAINT trade_review_removed_reason_not_blank CHECK (
        removed_reason IS NULL OR btrim(removed_reason) <> ''
    ),
    ADD CONSTRAINT trade_review_removal_basis_not_blank CHECK (
        removal_basis_ref IS NULL OR btrim(removal_basis_ref) <> ''
    );
