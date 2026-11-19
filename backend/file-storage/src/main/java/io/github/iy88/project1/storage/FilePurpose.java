package io.github.iy88.project1.storage;

public enum FilePurpose {
    PRODUCT_IMAGE("product_image"),
    CASE_EVIDENCE("case_evidence");

    private final String value;

    FilePurpose(String value) {
        this.value = value;
    }

    public String value() {
        return value;
    }

    public static FilePurpose fromValue(String value) {
        return switch (value) {
            case "product_image" -> PRODUCT_IMAGE;
            case "case_evidence" -> CASE_EVIDENCE;
            default -> throw new IllegalArgumentException("Unknown file purpose");
        };
    }
}
