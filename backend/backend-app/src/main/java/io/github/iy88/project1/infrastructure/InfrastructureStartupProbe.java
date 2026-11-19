package io.github.iy88.project1.infrastructure;

import java.time.Duration;
import java.util.UUID;

import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Profile;
import org.springframework.core.annotation.Order;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.util.Assert;

import lombok.RequiredArgsConstructor;

@Component
@Profile("infrastructure")
@EnableConfigurationProperties(RedisProbeProperties.class)
@Order(0)
@RequiredArgsConstructor
class InfrastructureStartupProbe implements ApplicationRunner {

    private static final Duration REDIS_PROBE_TTL = Duration.ofSeconds(30);

    private final InfrastructureProbeRepository repository;
    private final StringRedisTemplate redis;
    private final RedisProbeProperties redisProperties;

    @Override
    public void run(ApplicationArguments args) {
        var entry = repository.findById(1)
                .orElseThrow(() -> new IllegalStateException("PostgreSQL infrastructure probe row is missing"));

        String token = UUID.randomUUID().toString();
        String key = redisProperties.namespace() + ":probe:" + token;
        var values = redis.opsForValue();
        Assert.state(Boolean.TRUE.equals(values.setIfAbsent(key, token, REDIS_PROBE_TTL)),
                "Redis infrastructure probe could not create its key");
        try {
            Assert.state(token.equals(values.get(key)), "Redis infrastructure probe read an unexpected value");
        } finally {
            redis.delete(key);
        }
        LoggerFactory.getLogger(InfrastructureStartupProbe.class)
                .info("PostgreSQL schema validation and JPA query passed (probe row ID {}). Redis probe read, write and cleanup passed.",
                        entry.getId());
    }
}
