package io.github.iy88.project1.messaging;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.delivery")
public record DeliverySettings(int retentionSeconds, int replayMax, int leaseSeconds, int ioTimeoutSeconds,
                               int retryLimit, int retryBaseSeconds, int batchSize, int streamMaxLength) {
    public DeliverySettings {
        if (retentionSeconds < 3600 || retentionSeconds > 2_592_000 || replayMax < 1 || replayMax > 1000
                || ioTimeoutSeconds < 1 || leaseSeconds <= ioTimeoutSeconds
                || retryLimit < 1 || retryBaseSeconds < 1 || batchSize < 1 || batchSize > 1000
                || streamMaxLength < batchSize) {
            throw new IllegalArgumentException("Invalid event delivery or work settings");
        }
    }

    public int retryDelay(int attempts) {
        return (int) Math.min(300, (long) retryBaseSeconds << Math.min(Math.max(0, attempts - 1), 10));
    }
}
