package io.github.iy88.project1.infrastructure;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.Assert;

@ConfigurationProperties("project1.redis")
public record RedisProbeProperties(String namespace) {

    public RedisProbeProperties {
        Assert.isTrue(namespace != null && namespace.matches("[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*"),
                "REDIS_NAMESPACE must contain non-empty colon-separated segments using letters, digits, underscores or hyphens");
    }
}
