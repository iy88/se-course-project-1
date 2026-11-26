package io.github.iy88.project1.account.application;

import io.github.iy88.project1.core.BusinessError;
import java.util.Locale;
import java.util.regex.Pattern;

public final class EmailAddress {
    private static final Pattern SHAPE = Pattern.compile("^[^@\\s]{1,64}@[^@\\s]{1,190}$");

    private EmailAddress() {
    }

    public static String normalize(String value) {
        String email = value == null ? "" : value.trim();
        if (email.length() > 254 || !SHAPE.matcher(email).matches()) {
            throw new BusinessError("INPUT_INVALID", 422, "邮箱格式无效");
        }
        return email;
    }

    static boolean same(String left, String right) {
        return left != null && right != null
                && left.trim().toLowerCase(Locale.ROOT).equals(right.trim().toLowerCase(Locale.ROOT));
    }
}
