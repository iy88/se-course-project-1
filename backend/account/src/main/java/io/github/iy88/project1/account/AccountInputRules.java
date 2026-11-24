package io.github.iy88.project1.account;

import io.github.iy88.project1.core.BusinessError;

/** Account input rules shared by the HTTP application and the maintenance CLI. */
public record AccountInputRules(int passwordMinLength, int passwordMaxLength, int displayNameMaxLength) {
    public AccountInputRules {
        validateLimits(passwordMinLength, passwordMaxLength, displayNameMaxLength);
    }

    static void validateLimits(int passwordMinLength, int passwordMaxLength, int displayNameMaxLength) {
        if (passwordMinLength < 8 || passwordMaxLength < passwordMinLength || passwordMaxLength > 1024) {
            throw new IllegalArgumentException("Invalid password length settings");
        }
        if (displayNameMaxLength < 1 || displayNameMaxLength > 256) {
            throw new IllegalArgumentException("Invalid display name length setting");
        }
    }

    public String displayName(String value) {
        String name = value == null ? "" : value.trim();
        if (name.isEmpty() || name.codePointCount(0, name.length()) > displayNameMaxLength) {
            throw new BusinessError("INPUT_INVALID", 422, "显示名称无效");
        }
        return name;
    }

    public void requirePassword(CharSequence password) {
        int length = password == null ? 0 : Character.codePointCount(password, 0, password.length());
        if (length < passwordMinLength || length > passwordMaxLength) {
            throw new BusinessError("INPUT_INVALID", 422, "密码长度不符合要求");
        }
    }
}
