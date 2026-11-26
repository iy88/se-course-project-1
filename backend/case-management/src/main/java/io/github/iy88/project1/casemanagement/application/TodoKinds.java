package io.github.iy88.project1.casemanagement.application;

/** Legal management-todo kinds defined by the shared query contract for this stage. */
public final class TodoKinds {
    public static final String PRODUCT_REVIEW = "product_review";
    public static final String REPORT = "report";
    public static final String DISPUTE = "dispute";
    public static final String EXCEPTION = "exception";
    public static final String ALL_KINDS = "all";
    public static final java.util.List<String> ALL = java.util.List.of(PRODUCT_REVIEW, REPORT, DISPUTE, EXCEPTION);

    private TodoKinds() {
    }

    public static boolean legal(String kind) {
        return ALL.contains(kind);
    }
}
