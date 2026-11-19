package io.github.iy88.project1.infrastructure;

import java.time.Duration;
import java.util.UUID;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.annotation.Order;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.util.Assert;

@Component
@Profile("infrastructure")
@Order(0)
class InfrastructureStartupProbe implements ApplicationRunner {

    private static final Duration REDIS_PROBE_TTL = Duration.ofSeconds(30);

    private final InfrastructureProbeRepository repository;
    private final StringRedisTemplate redis;
    private final String redisNamespace;

    InfrastructureStartupProbe(
            InfrastructureProbeRepository repository,
            StringRedisTemplate redis,
            @Value("${project1.redis.namespace}") String redisNamespace) {
        Assert.isTrue(redisNamespace.matches("[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*"),
                "REDIS_NAMESPACE must contain non-empty colon-separated segments using letters, digits, underscores or hyphens");
        this.repository = repository;
        this.redis = redis;
        this.redisNamespace = redisNamespace;
    }

    @Override
    public void run(ApplicationArguments args) {
        Assert.state(repository.existsById(1), "PostgreSQL infrastructure probe row is missing");

        String token = UUID.randomUUID().toString();
        String key = redisNamespace + ":probe:" + token;
        var values = redis.opsForValue();
        Assert.state(Boolean.TRUE.equals(values.setIfAbsent(key, token, REDIS_PROBE_TTL)),
                "Redis infrastructure probe could not create its key");
        try {
            Assert.state(token.equals(values.get(key)), "Redis infrastructure probe read an unexpected value");
        } finally {
            redis.delete(key);
        }
        LoggerFactory.getLogger(InfrastructureStartupProbe.class)
                .info("PostgreSQL schema validation and JPA query passed. Redis probe read, write and cleanup passed.");
    }
}
