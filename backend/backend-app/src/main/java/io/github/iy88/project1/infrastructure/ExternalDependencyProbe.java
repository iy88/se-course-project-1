package io.github.iy88.project1.infrastructure;

import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Profile;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

@Component
@Profile("dependency-probe")
@EnableConfigurationProperties(ExternalProbeProperties.class)
@Order(1)
class ExternalDependencyProbe implements ApplicationRunner {

    private final ExternalProbeProperties properties;
    private final SmtpProbeRecipient recipient;

    ExternalDependencyProbe(ExternalProbeProperties properties, SmtpProbeRecipient recipient) {
        this.properties = properties;
        this.recipient = recipient;
    }

    @Override
    public void run(ApplicationArguments args) {
        OssConnectivityProbe.verify(properties.oss());
        var logger = LoggerFactory.getLogger(ExternalDependencyProbe.class);
        logger.info("OSS private bucket, versioning, object write, read and cleanup passed.");
        String probeId = SmtpConnectivityProbe.send(properties.smtp(), recipient);
        logger.info("SMTP server accepted test message {}.", probeId);
    }
}
