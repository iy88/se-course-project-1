-- Categories, category names and the prohibited-item scope.

CREATE OR REPLACE FUNCTION normalize_category_name(value TEXT) RETURNS TEXT
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
SELECT lower(regexp_replace(btrim(value), '\s+', ' ', 'g'))
$$;

CREATE TABLE category (
    category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_by_admin_id BIGINT NOT NULL REFERENCES account (account_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    disabled_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CHECK (disabled_at IS NULL OR disabled_at >= created_at),
    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE TABLE category_name (
    category_name_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id BIGINT NOT NULL REFERENCES category (category_id),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    name_kind TEXT NOT NULL CHECK (name_kind IN ('main', 'alias')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deactivated_at TIMESTAMPTZ,
    CHECK (deactivated_at IS NULL OR deactivated_at >= created_at)
);

CREATE UNIQUE INDEX category_name_active_key
    ON category_name (normalize_category_name(name))
    WHERE deactivated_at IS NULL;
CREATE UNIQUE INDEX category_name_active_main_key
    ON category_name (category_id)
    WHERE deactivated_at IS NULL AND name_kind = 'main';
CREATE INDEX category_name_category_idx ON category_name (category_id, category_name_id);

CREATE TABLE banned_item (
    banned_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_group TEXT NOT NULL CHECK (item_group IN ('legal_prohibited', 'dangerous_controlled',
        'live_animals', 'medicine_device', 'account_virtual', 'service_promotion', 'other')),
    content TEXT NOT NULL CHECK (btrim(content) <> ''),
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    updated_by_admin_id BIGINT NOT NULL REFERENCES account (account_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    deleted_at TIMESTAMPTZ,
    CHECK (deleted_at IS NULL OR deleted_at >= updated_at)
);

CREATE INDEX banned_item_active_idx ON banned_item (display_order, banned_item_id)
    WHERE deleted_at IS NULL;

CREATE TABLE banned_scope_state (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp()
);
INSERT INTO banned_scope_state VALUES (true, statement_timestamp());
