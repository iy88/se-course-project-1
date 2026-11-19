package io.github.iy88.project1.infrastructure;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.data.redis.core.StringRedisTemplate;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
class InfrastructureProbeConfiguration {

    @Bean
    public InfrastructureStartupProbe infrastructureStartupProbe(
            InfrastructureProbeRepository repository,
            StringRedisTemplate redis,
            @Value("${project1.redis.namespace}") String redisNamespace) {
        return new InfrastructureStartupProbe(repository, redis, redisNamespace);
    }
}
