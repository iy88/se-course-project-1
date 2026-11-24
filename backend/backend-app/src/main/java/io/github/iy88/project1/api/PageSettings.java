package io.github.iy88.project1.api;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.api")
public record PageSettings(int pageSizeDefault, int pageSizeMax) {
    public PageSettings {
        if (pageSizeDefault < 1 || pageSizeMax < pageSizeDefault) {
            throw new IllegalArgumentException("Invalid shared pagination settings");
        }
    }
}
