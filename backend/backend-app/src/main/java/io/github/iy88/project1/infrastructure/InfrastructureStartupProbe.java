package io.github.iy88.project1.infrastructure;

import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.util.Assert;

@Component
@Profile("infrastructure")
class InfrastructureStartupProbe implements ApplicationRunner {

    private final InfrastructureProbeRepository repository;

    InfrastructureStartupProbe(InfrastructureProbeRepository repository) {
        this.repository = repository;
    }

    @Override
    public void run(ApplicationArguments args) {
        Assert.state(repository.existsById(1), "PostgreSQL infrastructure probe row is missing");
        LoggerFactory.getLogger(InfrastructureStartupProbe.class).info("PostgreSQL migration and JPA query passed.");
    }
}
