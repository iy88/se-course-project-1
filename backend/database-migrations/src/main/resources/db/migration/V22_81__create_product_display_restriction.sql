-- Product display restrictions (S4-01, issue #81).
--
-- A display restriction is independent from the product lifecycle and occupancy. Removing one
-- source only releases that source; any other active source keeps the product hidden. Released
-- rows stay for traceability.

CREATE TABLE product_display_restriction (
    restriction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES product (product_id),
    source_type TEXT NOT NULL CHECK (source_type IN ('admin_case', 'account_ban')),
    source_ref_id BIGINT NOT NULL CHECK (source_ref_id > 0),
    reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
    basis_ref TEXT NOT NULL CHECK (btrim(basis_ref) <> ''),
    created_by BIGINT NOT NULL CHECK (created_by > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    released_at TIMESTAMPTZ,
    released_by BIGINT CHECK (released_by IS NULL OR released_by > 0),
    release_reason TEXT CHECK (release_reason IS NULL OR btrim(release_reason) <> ''),
    release_basis_ref TEXT CHECK (release_basis_ref IS NULL OR btrim(release_basis_ref) <> ''),
    CHECK ((released_at IS NULL) = (released_by IS NULL)),
    CHECK ((released_at IS NULL) = (release_reason IS NULL)),
    CHECK ((released_at IS NULL) = (release_basis_ref IS NULL))
);

-- One active row per product and source. The partial key also serves the public-read predicate
-- "no active restriction for this product"; released rows are append-only history.
CREATE UNIQUE INDEX product_display_restriction_active_key
    ON product_display_restriction (product_id, source_type, source_ref_id)
    WHERE released_at IS NULL;
