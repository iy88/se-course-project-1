package io.github.iy88.project1.account;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.account")
public record AccountSettings(
        int passwordMinLength,
        int passwordMaxLength,
        int displayNameMaxLength,
        int sessionAbsoluteSeconds,
        int sessionIdleSeconds,
        int sessionRenewIntervalSeconds,
        int emailCodeLength,
        int emailCodeTtlSeconds,
        int emailCodeMaxFailedAttempts,
        int emailResendIntervalSeconds,
        int entryTtlSeconds,
        String entrySigningKey,
        String entryKeyVersion) {

    public AccountSettings {
        AccountInputRules.validateLimits(passwordMinLength, passwordMaxLength, displayNameMaxLength);
        if (sessionAbsoluteSeconds < 1 || sessionIdleSeconds < 1 || sessionIdleSeconds > sessionAbsoluteSeconds
                || sessionRenewIntervalSeconds < 1 || sessionRenewIntervalSeconds >= sessionIdleSeconds) {
            throw new IllegalArgumentException("Invalid session duration settings");
        }
        if (emailCodeLength < 6 || emailCodeLength > 10 || emailCodeTtlSeconds < 60 || emailCodeTtlSeconds > 1800
                || emailCodeMaxFailedAttempts < 1 || emailCodeMaxFailedAttempts > 20
                || emailResendIntervalSeconds < 1 || emailResendIntervalSeconds > 600) {
            throw new IllegalArgumentException("Invalid email verification settings");
        }
        if (entryTtlSeconds <= emailCodeTtlSeconds) {
            throw new IllegalArgumentException("Account entry must outlive the email code");
        }
        if (entrySigningKey == null || entrySigningKey.getBytes(java.nio.charset.StandardCharsets.UTF_8).length < 32
                || entryKeyVersion == null || entryKeyVersion.isBlank()) {
            throw new IllegalArgumentException("ACCOUNT_ENTRY_SIGNING_KEY must contain at least 32 bytes");
        }
    }

    public AccountInputRules inputRules() {
        return new AccountInputRules(passwordMinLength, passwordMaxLength, displayNameMaxLength);
    }
}
