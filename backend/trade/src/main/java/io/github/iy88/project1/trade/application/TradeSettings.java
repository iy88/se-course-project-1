package io.github.iy88.project1.trade.application;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.trade")
public record TradeSettings(int confirmationWaitSeconds, String policyVersion, int pageSizeDefault, int pageSizeMax,
                            int historyLimit) {
    public TradeSettings {
        if (confirmationWaitSeconds < 1 || confirmationWaitSeconds > 2_592_000) {
            throw new IllegalArgumentException("project1.trade.confirmation-wait-seconds must be positive");
        }
        if (policyVersion == null || policyVersion.isBlank() || !policyVersion.matches("[a-z0-9][a-z0-9._-]{0,49}")) {
            throw new IllegalArgumentException("project1.trade.policy-version is invalid");
        }
        if (pageSizeDefault < 1 || pageSizeMax < pageSizeDefault || pageSizeMax > 1000
                || historyLimit < 1 || historyLimit > 1000) {
            throw new IllegalArgumentException("Invalid trade pagination settings");
        }
    }
}
