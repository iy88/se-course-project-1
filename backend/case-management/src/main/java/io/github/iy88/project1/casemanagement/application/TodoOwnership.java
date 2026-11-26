package io.github.iy88.project1.casemanagement.application;

/** Queue ownership filter. */
public enum TodoOwnership {
    UNCLAIMED, MINE, COMPLETED_ALL, COMPLETED_MINE;

    public static TodoOwnership parse(String value) {
        if (value == null) {
            return UNCLAIMED;
        }
        return switch (value) {
            case "unclaimed" -> UNCLAIMED;
            case "mine" -> MINE;
            case "completed_all" -> COMPLETED_ALL;
            case "completed_mine" -> COMPLETED_MINE;
            default -> throw new io.github.iy88.project1.core.BusinessError(
                    "INPUT_INVALID", 422, "待办归属无效");
        };
    }

}
