package io.github.iy88.project1.account;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.account")
public record EmailDeliverySettings(int emailSendBatchSize, int emailSendMaxAttempts, int emailLeaseSeconds,
                                    int emailSendRetrySeconds, int emailSendScanSeconds) {
    public EmailDeliverySettings {
        if (emailSendBatchSize < 1 || emailSendBatchSize > 200
                || emailSendMaxAttempts < 1 || emailSendMaxAttempts > 10
                || emailLeaseSeconds < 5 || emailLeaseSeconds > 300
                || emailSendRetrySeconds < 1 || emailSendRetrySeconds > 600
                || emailSendScanSeconds < 1 || emailSendScanSeconds > 300) {
            throw new IllegalArgumentException("Invalid email delivery settings");
        }
    }
}
