package io.github.iy88.project1.core;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.write")
public record WriteSettings(int lockTimeoutSeconds, int transactionTimeoutSeconds, int retryLimit,
                            int retryBaseMilliseconds, int idempotencyKeyMaxLength, int idempotencyRetentionSeconds) {
    public WriteSettings {
        if (lockTimeoutSeconds < 1 || transactionTimeoutSeconds <= lockTimeoutSeconds
                || retryLimit < 0 || retryLimit > 10 || retryBaseMilliseconds < 10 || retryBaseMilliseconds > 1000
                || idempotencyKeyMaxLength < 16 || idempotencyKeyMaxLength > 512 || idempotencyRetentionSeconds < 1) {
            throw new IllegalArgumentException("Invalid transaction or idempotency settings");
        }
    }
}
