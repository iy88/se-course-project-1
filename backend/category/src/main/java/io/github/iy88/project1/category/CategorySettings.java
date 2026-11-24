package io.github.iy88.project1.category;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.category")
public record CategorySettings(int nameMaxLength, int bannedContentMaxLength) {
    public CategorySettings {
        if (nameMaxLength < 1 || nameMaxLength > 200) {
            throw new IllegalArgumentException("Invalid category name length setting");
        }
        if (bannedContentMaxLength < 1 || bannedContentMaxLength > 1000) {
            throw new IllegalArgumentException("Invalid banned content length setting");
        }
    }
}
