-- Conversation module schema (API-CONV-001..005).
-- Cross-module foreign keys (account, trade, case) are added once the S2/S4
-- baseline that owns those tables is merged; this migration only creates the
-- conversation-owned tables so it can run on the S1 skeleton independently.

CREATE TABLE chat_conversation (
    chat_conversation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_low_id BIGINT NOT NULL CHECK (account_low_id > 0),
    account_high_id BIGINT NOT NULL CHECK (account_high_id > account_low_id),
    seq_head BIGINT NOT NULL DEFAULT 0 CHECK (seq_head BETWEEN 0 AND 9007199254740991),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (account_low_id, account_high_id)
);

CREATE TABLE trade_conversation (
    trade_conversation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_id BIGINT NOT NULL UNIQUE CHECK (trade_id > 0),
    seq_head BIGINT NOT NULL DEFAULT 0 CHECK (seq_head BETWEEN 0 AND 9007199254740991),
    created_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ
);

CREATE TABLE case_conversation (
    case_conversation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id BIGINT NOT NULL CHECK (case_id > 0),
    related_account_id BIGINT NOT NULL CHECK (related_account_id > 0),
    seq_head BIGINT NOT NULL DEFAULT 0 CHECK (seq_head BETWEEN 0 AND 9007199254740991),
    created_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ,
    UNIQUE (case_id, related_account_id)
);

CREATE TABLE chat_message (
    chat_message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_conversation_id BIGINT NOT NULL REFERENCES chat_conversation (chat_conversation_id),
    seq BIGINT NOT NULL CHECK (seq > 0),
    sender_account_id BIGINT NOT NULL CHECK (sender_account_id > 0),
    body TEXT NOT NULL CHECK (btrim(body) <> ''),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (chat_conversation_id, seq)
);

CREATE TABLE trade_message (
    trade_message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_conversation_id BIGINT NOT NULL REFERENCES trade_conversation (trade_conversation_id),
    seq BIGINT NOT NULL CHECK (seq > 0),
    sender_kind TEXT NOT NULL CHECK (sender_kind IN ('account', 'system')),
    sender_account_id BIGINT CHECK (sender_account_id > 0),
    message_type TEXT NOT NULL CHECK (message_type IN ('text', 'system_event')),
    body TEXT NOT NULL CHECK (btrim(body) <> ''),
    business_event_id UUID,
    event_type TEXT,
    source_type TEXT,
    source_id BIGINT CHECK (source_id > 0),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (trade_conversation_id, seq),
    CHECK ((sender_kind = 'system') = (sender_account_id IS NULL)),
    CHECK ((sender_kind = 'system') = (message_type = 'system_event')),
    CHECK ((sender_kind = 'system') = (business_event_id IS NOT NULL)),
    CHECK ((business_event_id IS NULL) = (event_type IS NULL)),
    CHECK ((source_type IS NULL) = (source_id IS NULL)),
    CHECK (business_event_id IS NULL OR event_type IS NOT NULL)
);

CREATE UNIQUE INDEX trade_message_business_event_idx
    ON trade_message (business_event_id) WHERE business_event_id IS NOT NULL;

CREATE TABLE case_message (
    case_message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_conversation_id BIGINT NOT NULL REFERENCES case_conversation (case_conversation_id),
    seq BIGINT NOT NULL CHECK (seq > 0),
    message_kind TEXT NOT NULL CHECK (message_kind IN
        ('inquiry', 'statement', 'appeal', 'manager_reply', 'system_notice')),
    sender_kind TEXT NOT NULL CHECK (sender_kind IN ('account', 'manager', 'system')),
    sender_account_id BIGINT CHECK (sender_account_id > 0),
    body TEXT NOT NULL CHECK (btrim(body) <> ''),
    business_event_id UUID,
    event_type TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (case_conversation_id, seq),
    CHECK ((sender_kind = 'system') = (sender_account_id IS NULL)),
    CHECK ((message_kind = 'system_notice') = (sender_kind = 'system')),
    CHECK ((sender_kind = 'system') = (business_event_id IS NOT NULL)),
    CHECK ((business_event_id IS NULL) = (event_type IS NULL)),
    CHECK (sender_kind <> 'account' OR message_kind IN ('statement', 'appeal')),
    CHECK (sender_kind <> 'manager' OR message_kind IN ('inquiry', 'manager_reply'))
);

CREATE UNIQUE INDEX case_message_business_event_idx
    ON case_message (business_event_id) WHERE business_event_id IS NOT NULL;

CREATE TABLE chat_read_progress (
    chat_conversation_id BIGINT NOT NULL REFERENCES chat_conversation (chat_conversation_id),
    account_id BIGINT NOT NULL CHECK (account_id > 0),
    last_read_seq BIGINT NOT NULL DEFAULT 0 CHECK (last_read_seq BETWEEN 0 AND 9007199254740991),
    last_read_at TIMESTAMPTZ,
    PRIMARY KEY (chat_conversation_id, account_id),
    CHECK ((last_read_seq = 0) = (last_read_at IS NULL))
);

CREATE TABLE trade_read_progress (
    trade_conversation_id BIGINT NOT NULL REFERENCES trade_conversation (trade_conversation_id),
    account_id BIGINT NOT NULL CHECK (account_id > 0),
    last_read_seq BIGINT NOT NULL DEFAULT 0 CHECK (last_read_seq BETWEEN 0 AND 9007199254740991),
    last_read_at TIMESTAMPTZ,
    PRIMARY KEY (trade_conversation_id, account_id),
    CHECK ((last_read_seq = 0) = (last_read_at IS NULL))
);

CREATE TABLE case_read_progress (
    case_conversation_id BIGINT NOT NULL REFERENCES case_conversation (case_conversation_id),
    account_id BIGINT NOT NULL CHECK (account_id > 0),
    last_read_seq BIGINT NOT NULL DEFAULT 0 CHECK (last_read_seq BETWEEN 0 AND 9007199254740991),
    last_read_at TIMESTAMPTZ,
    PRIMARY KEY (case_conversation_id, account_id),
    CHECK ((last_read_seq = 0) = (last_read_at IS NULL))
);
