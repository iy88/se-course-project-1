-- Trade request lifecycle. Cross-domain identifiers (product, account, case) intentionally
-- have no foreign keys here: their owning modules provide them in the same database.

CREATE TABLE trade (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL CHECK (product_id > 0),
    buyer_id BIGINT NOT NULL CHECK (buyer_id > 0),
    seller_id BIGINT NOT NULL CHECK (seller_id > 0),
    status TEXT NOT NULL CHECK (status IN (
        'pending_acceptance', 'rejected', 'withdrawn', 'closed', 'in_progress',
        'disputed', 'abnormal', 'terminated', 'completed'
    )),
    request_note VARCHAR(500),
    active_agreement_id BIGINT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    close_reason TEXT CHECK (close_reason IS NULL OR close_reason IN (
        'other_user_locked', 'product_delisted', 'public_access_revoked', 'account_banned'
    )),
    terminal_reason TEXT CHECK (terminal_reason IS NULL OR terminal_reason IN (
        'completed', 'cancelled', 'admin_terminated'
    )),
    requested_at TIMESTAMPTZ NOT NULL,
    responded_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (buyer_id <> seller_id),
    CHECK ((close_reason IS NOT NULL) = (status = 'closed')),
    CHECK ((terminal_reason IS NOT NULL) = (status IN ('completed', 'terminated'))),
    CHECK ((ended_at IS NOT NULL) = (status IN ('completed', 'terminated')))
);

CREATE UNIQUE INDEX trade_pending_buyer_idx ON trade (product_id, buyer_id)
    WHERE status = 'pending_acceptance';
CREATE UNIQUE INDEX trade_product_occupancy_idx ON trade (product_id)
    WHERE status IN ('in_progress', 'disputed', 'abnormal');
CREATE INDEX trade_product_status_idx ON trade (product_id, status);
CREATE INDEX trade_buyer_updated_idx ON trade (buyer_id, status, updated_at DESC, id DESC);
CREATE INDEX trade_seller_updated_idx ON trade (seller_id, status, updated_at DESC, id DESC);
CREATE INDEX trade_status_updated_idx ON trade (status, updated_at DESC, id DESC);

CREATE TABLE trade_item_snapshot (
    trade_id BIGINT PRIMARY KEY REFERENCES trade (id),
    product_id BIGINT NOT NULL CHECK (product_id > 0),
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL CHECK (char_length(description) <= 5000),
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
    category_names TEXT[] NOT NULL DEFAULT '{}',
    image_file_ids BIGINT[] NOT NULL DEFAULT '{}',
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE agreement_version (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    base_agreement_id BIGINT,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    status TEXT NOT NULL CHECK (status IN ('proposed', 'effective', 'rejected', 'withdrawn', 'superseded')),
    proposed_by BIGINT NOT NULL CHECK (proposed_by > 0),
    delivery_at TIMESTAMPTZ NOT NULL,
    delivery_place_text VARCHAR(200) NOT NULL,
    delivery_method VARCHAR(100) NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    payment_method VARCHAR(100) NOT NULL,
    payment_timing VARCHAR(100) NOT NULL,
    proposed_at TIMESTAMPTZ NOT NULL,
    business_event_id UUID NOT NULL UNIQUE,
    UNIQUE (trade_id, version_no),
    UNIQUE (id, trade_id),
    CHECK (base_agreement_id IS NULL OR base_agreement_id <> id),
    FOREIGN KEY (base_agreement_id, trade_id) REFERENCES agreement_version (id, trade_id)
);

CREATE UNIQUE INDEX agreement_version_proposed_idx ON agreement_version (trade_id)
    WHERE status = 'proposed';
CREATE UNIQUE INDEX agreement_version_effective_idx ON agreement_version (trade_id)
    WHERE status = 'effective';
CREATE INDEX agreement_version_trade_idx ON agreement_version (trade_id, id);

ALTER TABLE trade ADD CONSTRAINT trade_active_agreement_fk
    FOREIGN KEY (active_agreement_id, id) REFERENCES agreement_version (id, trade_id);

CREATE TABLE agreement_decision (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agreement_id BIGINT NOT NULL UNIQUE REFERENCES agreement_version (id),
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'withdraw')),
    actor_id BIGINT NOT NULL CHECK (actor_id > 0),
    decided_at TIMESTAMPTZ NOT NULL,
    business_event_id UUID NOT NULL UNIQUE
);

CREATE TABLE cancellation_proposal (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    proposed_by BIGINT NOT NULL CHECK (proposed_by > 0),
    mode TEXT NOT NULL CHECK (mode IN ('direct', 'approval')),
    reason VARCHAR(500),
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'withdrawn')),
    proposed_at TIMESTAMPTZ NOT NULL,
    business_event_id UUID NOT NULL UNIQUE,
    UNIQUE (id, trade_id)
);

CREATE UNIQUE INDEX cancellation_proposal_pending_idx ON cancellation_proposal (trade_id)
    WHERE status = 'pending';
CREATE INDEX cancellation_proposal_trade_idx ON cancellation_proposal (trade_id, id);

CREATE TABLE cancellation_decision (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cancellation_id BIGINT NOT NULL UNIQUE REFERENCES cancellation_proposal (id),
    decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'withdraw')),
    actor_id BIGINT NOT NULL CHECK (actor_id > 0),
    decided_at TIMESTAMPTZ NOT NULL,
    business_event_id UUID NOT NULL UNIQUE
);

CREATE TABLE trade_dispute (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    initiator_id BIGINT NOT NULL CHECK (initiator_id > 0),
    statement VARCHAR(2000) NOT NULL CHECK (btrim(statement) <> ''),
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'terminated')),
    resolution_mode TEXT CHECK (resolution_mode IS NULL OR resolution_mode IN ('self', 'admin')),
    resolved_by BIGINT CHECK (resolved_by IS NULL OR resolved_by > 0),
    case_id BIGINT CHECK (case_id IS NULL OR case_id > 0),
    opened_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    UNIQUE (id, trade_id),
    CHECK ((status = 'open') = (resolved_at IS NULL)),
    CHECK ((status = 'open' AND resolution_mode IS NULL AND resolved_by IS NULL)
        OR (status = 'resolved' AND resolution_mode IS NOT NULL AND resolved_by IS NOT NULL)
        OR status = 'terminated'),
    CHECK (resolution_mode IS DISTINCT FROM 'admin' OR case_id IS NOT NULL)
);

CREATE UNIQUE INDEX trade_dispute_open_idx ON trade_dispute (trade_id) WHERE status = 'open';
CREATE INDEX trade_dispute_trade_idx ON trade_dispute (trade_id, id);

CREATE TABLE dispute_resolution_confirmation (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispute_id BIGINT NOT NULL REFERENCES trade_dispute (id),
    confirmer_id BIGINT NOT NULL CHECK (confirmer_id > 0),
    confirmed_at TIMESTAMPTZ NOT NULL,
    business_event_id UUID NOT NULL UNIQUE,
    UNIQUE (dispute_id, confirmer_id)
);

CREATE TABLE trade_confirmation (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    agreement_id BIGINT NOT NULL,
    confirmer_id BIGINT NOT NULL CHECK (confirmer_id > 0),
    note VARCHAR(1000),
    submitted_at TIMESTAMPTZ NOT NULL,
    invalidated_at TIMESTAMPTZ,
    invalidation_reason TEXT CHECK (invalidation_reason IS NULL OR invalidation_reason IN (
        'agreement_changed', 'dispute_resolved', 'admin_restored'
    )),
    business_event_id UUID NOT NULL UNIQUE,
    UNIQUE (id, trade_id),
    FOREIGN KEY (agreement_id, trade_id) REFERENCES agreement_version (id, trade_id),
    CHECK ((invalidated_at IS NULL) = (invalidation_reason IS NULL))
);

CREATE UNIQUE INDEX trade_confirmation_current_idx ON trade_confirmation (trade_id, confirmer_id)
    WHERE invalidated_at IS NULL;
CREATE INDEX trade_confirmation_trade_idx ON trade_confirmation (trade_id, id);

CREATE TABLE confirmation_wait (
    trade_id BIGINT PRIMARY KEY REFERENCES trade (id),
    started_at TIMESTAMPTZ NOT NULL,
    active_since TIMESTAMPTZ,
    accumulated_seconds INTEGER NOT NULL DEFAULT 0 CHECK (accumulated_seconds >= 0),
    wait_seconds INTEGER NOT NULL CHECK (wait_seconds > 0),
    policy_version VARCHAR(50) NOT NULL,
    ended_at TIMESTAMPTZ,
    end_reason TEXT CHECK (end_reason IS NULL OR end_reason IN (
        'completed', 'agreement_changed', 'disputed', 'terminated', 'timeout', 'admin_restored'
    )),
    CHECK (active_since IS NULL OR (ended_at IS NULL AND started_at <= active_since)),
    CHECK ((ended_at IS NULL) = (end_reason IS NULL)),
    CHECK (ended_at IS NULL OR active_since IS NULL)
);

CREATE TABLE trade_freeze (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    source TEXT NOT NULL CHECK (source IN ('timeout', 'admin_case', 'account_ban')),
    source_ref BIGINT CHECK (source_ref IS NULL OR source_ref > 0),
    reason VARCHAR(500) NOT NULL CHECK (btrim(reason) <> ''),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    ended_by BIGINT CHECK (ended_by IS NULL OR ended_by > 0),
    CHECK (source = 'account_ban' OR source_ref IS NOT NULL),
    CHECK (ended_by IS NULL OR ended_at IS NOT NULL)
);

CREATE UNIQUE INDEX trade_freeze_active_source_idx
    ON trade_freeze (trade_id, source, coalesce(source_ref, 0)) WHERE ended_at IS NULL;
CREATE INDEX trade_freeze_trade_idx ON trade_freeze (trade_id, id);

CREATE TABLE trade_state_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL REFERENCES trade (id),
    action VARCHAR(50) NOT NULL,
    from_status TEXT CHECK (from_status IS NULL OR from_status IN (
        'pending_acceptance', 'rejected', 'withdrawn', 'closed', 'in_progress',
        'disputed', 'abnormal', 'terminated', 'completed'
    )),
    to_status TEXT CHECK (to_status IS NULL OR to_status IN (
        'pending_acceptance', 'rejected', 'withdrawn', 'closed', 'in_progress',
        'disputed', 'abnormal', 'terminated', 'completed'
    )),
    from_phase TEXT CHECK (from_phase IS NULL OR from_phase IN ('first_agreement_pending', 'awaiting_completion')),
    to_phase TEXT CHECK (to_phase IS NULL OR to_phase IN ('first_agreement_pending', 'awaiting_completion')),
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('buyer', 'seller', 'admin', 'system')),
    actor_id BIGINT CHECK (actor_id IS NULL OR actor_id > 0),
    reason VARCHAR(500),
    basis_ref VARCHAR(200),
    case_id BIGINT CHECK (case_id IS NULL OR case_id > 0),
    agreement_id BIGINT,
    agreement_decision_id BIGINT,
    confirmation_id BIGINT,
    cancellation_id BIGINT,
    cancellation_decision_id BIGINT,
    dispute_id BIGINT,
    dispute_resolution_confirmation_id BIGINT,
    business_event_id UUID NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (agreement_id, trade_id) REFERENCES agreement_version (id, trade_id),
    FOREIGN KEY (confirmation_id, trade_id) REFERENCES trade_confirmation (id, trade_id),
    FOREIGN KEY (dispute_id, trade_id) REFERENCES trade_dispute (id, trade_id),
    FOREIGN KEY (cancellation_id) REFERENCES cancellation_proposal (id),
    FOREIGN KEY (agreement_decision_id) REFERENCES agreement_decision (id),
    FOREIGN KEY (cancellation_decision_id) REFERENCES cancellation_decision (id),
    FOREIGN KEY (dispute_resolution_confirmation_id) REFERENCES dispute_resolution_confirmation (id)
);

CREATE INDEX trade_state_history_trade_idx ON trade_state_history (trade_id, id);
