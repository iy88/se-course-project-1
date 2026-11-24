package io.github.iy88.project1.casemanagement.application;

/**
 * Read-only case columns that product adapters may join in a queue query. These names are a
 * handover contract; product adapters must not write the case tables.
 */
public final class ReviewCaseSchema {
    public static final String CASE_TABLE = "moderation_case";
    public static final String CASE_ID = "id";
    public static final String CASE_TYPE = "case_type";
    public static final String CASE_CREATED_AT = "created_at";
    public static final String CASE_CLAIMED_MANAGER_ID = "claimed_manager_id";
    public static final String CASE_CLAIMED_AT = "claimed_at";

    private ReviewCaseSchema() {
    }
}
