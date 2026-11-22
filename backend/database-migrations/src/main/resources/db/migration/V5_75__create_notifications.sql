-- C3 notification persistence (API-COM-NOTIFY-001—004).
--
-- One row per recipient account and intent. The unique scope is exactly the
-- contract's idempotency scope, so a retried business action cannot produce a
-- second notification and a different intent under the same key is rejected by
-- the application layer after a read of the existing row.
--
-- `read_at` records the first read only; later reads reuse the stored value.
-- The rendered summary is not stored: it is projected at read time from the
-- notification source's current visibility, so a notification never keeps
-- showing content the recipient may no longer see.
CREATE TABLE notification (
    notification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_account_id BIGINT NOT NULL CHECK (recipient_account_id > 0),
    intent_key TEXT NOT NULL CHECK (length(intent_key) BETWEEN 1 AND 200),
    event_type TEXT NOT NULL CHECK (length(event_type) BETWEEN 1 AND 120),
    business_event_id UUID,
    source_type TEXT NOT NULL CHECK (length(source_type) BETWEEN 1 AND 60),
    source_id BIGINT NOT NULL CHECK (source_id > 0),
    template_key TEXT NOT NULL CHECK (length(template_key) BETWEEN 1 AND 120),
    template_version TEXT NOT NULL CHECK (length(template_version) BETWEEN 1 AND 60),
    display_params JSONB NOT NULL CHECK (jsonb_typeof(display_params) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    read_at TIMESTAMPTZ,
    UNIQUE (recipient_account_id, intent_key),
    CHECK (created_at >= occurred_at),
    CHECK (read_at IS NULL OR read_at >= created_at)
);

-- List paging is descending by notification_id per recipient.
CREATE INDEX notification_recipient_idx
    ON notification (recipient_account_id, notification_id DESC);

-- Unread total is computed without touching read rows.
CREATE INDEX notification_unread_idx
    ON notification (recipient_account_id, notification_id DESC)
    WHERE read_at IS NULL;

-- Event filtering is optional and applied before paging.
CREATE INDEX notification_recipient_event_idx
    ON notification (recipient_account_id, event_type, notification_id DESC);
