-- Case lifecycle (S4-04, issue #84).
--
-- The shared case row keeps product-review rows unchanged. Report, dispute and exception rows
-- carry the target, reporter, decision, appeal and anonymous-publication facts here. Actions are
-- append-only; the existing product-review claim and decision facts stay in place.

ALTER TABLE moderation_case
    ADD COLUMN target_type TEXT,
    ADD COLUMN target_id BIGINT,
    ADD COLUMN target_conversation_kind TEXT,
    ADD COLUMN target_conversation_id BIGINT,
    ADD COLUMN reporter_account_id BIGINT,
    ADD COLUMN reported_reason TEXT,
    ADD COLUMN case_status TEXT,
    ADD COLUMN decision_kind TEXT,
    ADD COLUMN reason_text TEXT,
    ADD COLUMN decided_by BIGINT,
    ADD COLUMN decided_at TIMESTAMPTZ,
    ADD COLUMN archived_at TIMESTAMPTZ,
    ADD COLUMN public_summary TEXT,
    ADD COLUMN public_reason TEXT,
    ADD COLUMN public_result_at TIMESTAMPTZ,
    ADD COLUMN published_by BIGINT,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp();

UPDATE moderation_case SET updated_at = created_at;

-- Preserve the S3 trade links while projecting existing cases into the lifecycle.
UPDATE moderation_case c
SET target_type = 'trade',
    target_id = links.trade_id,
    case_status = CASE WHEN c.claimed_manager_id IS NULL THEN 'pending' ELSE 'claimed' END
FROM (
    SELECT case_id, trade_id FROM trade_timeout_case
    UNION ALL
    SELECT case_id, trade_id FROM trade_dispute_case
) links
WHERE c.id = links.case_id;

ALTER TABLE moderation_case
    ADD CONSTRAINT moderation_case_status_known
        CHECK (case_status IS NULL OR case_status IN ('pending', 'claimed', 'decided')),
    ADD CONSTRAINT moderation_case_lifecycle_status
        CHECK (case_type = 'product_review' OR case_status IS NOT NULL),
    ADD CONSTRAINT moderation_case_report_shape
        CHECK (case_type <> 'report'
            OR (reporter_account_id IS NOT NULL AND reported_reason IS NOT NULL
                AND target_type IS NOT NULL AND target_id IS NOT NULL)),
    ADD CONSTRAINT moderation_case_trade_target
        CHECK (case_type NOT IN ('dispute', 'exception')
            OR (target_type = 'trade' AND target_id IS NOT NULL)),
    ADD CONSTRAINT moderation_case_message_target
        CHECK (target_type <> 'message'
            OR (target_conversation_kind IS NOT NULL AND target_conversation_id IS NOT NULL)),
    ADD CONSTRAINT moderation_case_decision_shape
        CHECK (case_type = 'product_review'
            OR ((decision_kind IS NULL) = (decided_at IS NULL))
            AND ((decision_kind IS NULL) = (decided_by IS NULL))
            AND (decision_kind IS NULL OR decision_kind IN ('no_action', 'not_actionable', 'violation'))),
    ADD CONSTRAINT moderation_case_archive_after_decision
        CHECK (case_type = 'product_review' OR archived_at IS NULL OR case_status = 'decided'),
    ADD CONSTRAINT moderation_case_public_shape
        CHECK (case_type = 'report'
            OR (public_summary IS NULL AND public_reason IS NULL
                AND public_result_at IS NULL AND published_by IS NULL));

-- One open report per reporter and object; message targets additionally separate their branch.
CREATE UNIQUE INDEX moderation_case_open_report_object
    ON moderation_case (reporter_account_id, target_type, target_id)
    WHERE archived_at IS NULL AND case_type = 'report' AND target_type <> 'message';

CREATE UNIQUE INDEX moderation_case_open_report_message
    ON moderation_case (reporter_account_id, target_conversation_kind, target_id)
    WHERE archived_at IS NULL AND case_type = 'report' AND target_type = 'message';

CREATE INDEX moderation_case_reporter_idx
    ON moderation_case (reporter_account_id, updated_at DESC)
    WHERE reporter_account_id IS NOT NULL;

CREATE INDEX moderation_case_public_result_idx
    ON moderation_case (public_result_at DESC)
    WHERE public_result_at IS NOT NULL;

ALTER TABLE moderation_case_action
    ALTER COLUMN actor_account_id DROP NOT NULL,
    ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'manager',
    ADD COLUMN message_id BIGINT,
    ADD COLUMN related_account_id BIGINT,
    ADD COLUMN inquiry_action_id BIGINT,
    ADD COLUMN appeal_action_id BIGINT,
    ADD COLUMN resolution TEXT,
    ADD COLUMN note TEXT,
    ADD COLUMN basis_ref JSONB;

ALTER TABLE moderation_case_action
    ADD CONSTRAINT moderation_case_action_actor_known
        CHECK (actor_kind IN ('account', 'manager', 'system')),
    ADD CONSTRAINT moderation_case_action_resolution_known
        CHECK (resolution IS NULL OR resolution IN ('uphold', 'revoke', 'adjust')),
    ADD CONSTRAINT moderation_case_action_inquiry_only_with_note
        CHECK (action_kind <> 'inquire' OR note IS NOT NULL);

CREATE INDEX moderation_case_action_kind_idx ON moderation_case_action (action_kind, case_id);

-- One first answer per inquiry and one formal resolution per appeal.
CREATE UNIQUE INDEX moderation_case_action_statement_once
    ON moderation_case_action (case_id, inquiry_action_id)
    WHERE action_kind = 'statement' AND inquiry_action_id IS NOT NULL;

CREATE UNIQUE INDEX moderation_case_action_appeal_resolution_once
    ON moderation_case_action (case_id, appeal_action_id)
    WHERE action_kind = 'manager_reply' AND appeal_action_id IS NOT NULL;

CREATE UNIQUE INDEX moderation_case_action_appeal_once
    ON moderation_case_action (case_id, actor_account_id)
    WHERE action_kind = 'appeal';

CREATE UNIQUE INDEX moderation_case_action_close_once
    ON moderation_case_action (case_id) WHERE action_kind = 'close';

CREATE UNIQUE INDEX moderation_case_action_publish_once
    ON moderation_case_action (case_id) WHERE action_kind = 'publish_result';

CREATE TABLE case_evidence (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES moderation_case (id),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('submitter_attachment', 'platform_record')),
    file_id BIGINT,
    file_reference_id BIGINT,
    source_ref_type TEXT,
    source_ref_id BIGINT,
    required_scope TEXT,
    submitted_by BIGINT,
    submitted_at TIMESTAMPTZ NOT NULL,
    CHECK (evidence_kind <> 'submitter_attachment'
        OR (file_id IS NOT NULL AND submitted_by IS NOT NULL)),
    CHECK (evidence_kind <> 'platform_record'
        OR (source_ref_type IS NOT NULL AND source_ref_id IS NOT NULL
            AND required_scope IS NOT NULL AND submitted_by IS NOT NULL)),
    CHECK ((source_ref_type IS NULL) = (source_ref_id IS NULL))
);

CREATE UNIQUE INDEX case_evidence_file_once
    ON case_evidence (case_id, file_id) WHERE file_id IS NOT NULL;

CREATE INDEX case_evidence_case_idx ON case_evidence (case_id, id);

CREATE TABLE case_appeal_eligibility (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES moderation_case (id),
    account_id BIGINT NOT NULL,
    appeal_deadline_at TIMESTAMPTZ NOT NULL,
    basis_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (case_id, account_id)
);

CREATE INDEX case_appeal_eligibility_deadline_idx
    ON case_appeal_eligibility (case_id, appeal_deadline_at);

CREATE TABLE case_enforcement (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    case_id BIGINT NOT NULL REFERENCES moderation_case (id),
    enforcement_id TEXT NOT NULL CHECK (enforcement_id <> ''),
    action TEXT NOT NULL CHECK (action <> ''),
    target_type TEXT NOT NULL,
    target_id BIGINT NOT NULL,
    basis_ref TEXT,
    requested_by BIGINT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    result_type TEXT,
    result_id BIGINT,
    result_status TEXT NOT NULL CHECK (result_status IN ('applied', 'replayed', 'failed')),
    previous_state TEXT,
    current_state TEXT,
    affected_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
    failure_code TEXT,
    failure_reason TEXT,
    lifted_at TIMESTAMPTZ,
    lift_reason TEXT,
    lifted_by BIGINT,
    occurred_at TIMESTAMPTZ NOT NULL,
    UNIQUE (case_id, enforcement_id),
    CHECK ((result_type IS NULL) = (result_id IS NULL)),
    CHECK (result_status <> 'failed' OR failure_code IS NOT NULL)
);

CREATE INDEX case_enforcement_case_idx ON case_enforcement (case_id, id);
