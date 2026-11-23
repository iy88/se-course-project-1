package io.github.iy88.project1.product;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.product")
public record ProductSettings(int titleMaxLength, int descriptionMaxLength, long priceMaxCents,
                              int pageSize, int pageSizeMax, int imageMaxCount, int commentMaxLength,
                              int commentRateLimitCount, int commentRateLimitWindowSeconds) {
    public ProductSettings {
        if (titleMaxLength < 1 || titleMaxLength > 500 || descriptionMaxLength < 1 || descriptionMaxLength > 50000
                || priceMaxCents < 1 || pageSize < 1 || pageSize > pageSizeMax || pageSizeMax > 1000
                || imageMaxCount < 0 || imageMaxCount > 50 || commentMaxLength < 1 || commentMaxLength > 5000
                || commentRateLimitCount < 1 || commentRateLimitCount > 1000
                || commentRateLimitWindowSeconds < 1 || commentRateLimitWindowSeconds > 86400) {
            throw new IllegalArgumentException("Invalid product settings");
        }
    }
}
