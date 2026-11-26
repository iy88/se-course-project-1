package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.core.BusinessError;
import java.util.List;

final class EntityIds {
    private EntityIds() {
    }

    static long requirePositive(String value, String field) {
        try {
            long id = Long.parseLong(value);
            if (id <= 0 || !Long.toString(id).equals(value)) {
                throw invalid(field);
            }
            return id;
        } catch (NumberFormatException malformed) {
            throw invalid(field);
        }
    }

    static List<Long> requirePositive(List<String> values, String field) {
        if (values == null) {
            return List.of();
        }
        return values.stream().map(value -> requirePositive(value, field)).toList();
    }

    private static BusinessError invalid(String field) {
        return new BusinessError("INPUT_INVALID", 422, field + " 无效");
    }
}
