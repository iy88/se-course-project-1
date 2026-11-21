CREATE TABLE enforcement_case_fixture (
    run_id UUID NOT NULL,
    case_id BIGINT NOT NULL,
    manager_id BIGINT NOT NULL,
    target_type TEXT NOT NULL,
    target_id BIGINT NOT NULL,
    basis_type TEXT NOT NULL,
    basis_id BIGINT NOT NULL,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_id, case_id));

CREATE TABLE enforcement_case_evidence_fixture (
    run_id UUID NOT NULL,
    case_id BIGINT NOT NULL,
    file_id BIGINT NOT NULL,
    submitted_by BIGINT NOT NULL,
    slot TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id, file_id));

CREATE TABLE enforcement_execution_fixture (
    run_id UUID NOT NULL,
    case_id BIGINT NOT NULL,
    enforcement_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id BIGINT NOT NULL,
    result_type TEXT NOT NULL,
    result_id BIGINT NOT NULL,
    previous_state TEXT,
    current_state TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (run_id, case_id, enforcement_id));

CREATE TABLE enforcement_subject_fixture (
    run_id UUID NOT NULL,
    subject TEXT NOT NULL,
    subject_id BIGINT NOT NULL,
    state TEXT NOT NULL,
    source_ref TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (run_id, subject, subject_id));

CREATE TABLE enforcement_scope_fixture (
    run_id UUID NOT NULL,
    account_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    trade_id BIGINT NOT NULL,
    request_id BIGINT NOT NULL,
    PRIMARY KEY (run_id, account_id, product_id, trade_id, request_id));
