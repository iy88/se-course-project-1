package io.github.iy88.project1.infrastructure;

import io.github.iy88.project1.messaging.DeliverySettings;
import io.github.iy88.project1.storage.persistence.FileCleanup;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class DeliveryAssemblyTests {
    private final ApplicationContextRunner context = new ApplicationContextRunner()
            .withUserConfiguration(SmtpDeliveryConfiguration.class, FileCleanupLoop.class)
            .withBean(DeliverySettings.class, () -> new DeliverySettings(3600, 500, 60, 10, 5, 2, 32, 10000))
            .withBean(FileCleanup.class, () -> mock(FileCleanup.class));

    @Test
    void businessApiAndWorkerLoadSmtpWithTheirNormalProfiles() {
        var configured = context.withPropertyValues(
                "SMTP_HOST=smtp.example.com", "SMTP_PORT=587", "SMTP_TLS_MODE=starttls",
                "SMTP_USERNAME=sender@example.com", "SMTP_PASSWORD=test-password", "SMTP_FROM=sender@example.com");
        configured.withPropertyValues("spring.profiles.active=infrastructure")
                .run(app -> assertThat(app).hasSingleBean(SmtpDelivery.class).doesNotHaveBean(FileCleanupLoop.class));
        configured.withPropertyValues("spring.profiles.active=infrastructure,delivery-worker")
                .run(app -> assertThat(app).hasSingleBean(SmtpDelivery.class).doesNotHaveBean(FileCleanupLoop.class));
    }

    @Test
    void schedulerLoadsOssCleanupWithItsNormalProfile() {
        context.withPropertyValues("spring.profiles.active=infrastructure,delivery-scheduler",
                        "OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com", "OSS_REGION=cn-hangzhou",
                        "OSS_BUCKET=project1-test", "OSS_PREFIX=project1/test",
                        "OSS_ACCESS_KEY_ID=test-key", "OSS_ACCESS_KEY_SECRET=test-secret")
                .run(app -> assertThat(app).hasSingleBean(FileCleanupLoop.class).doesNotHaveBean(SmtpDelivery.class));
    }

    @Test
    void missingRoleConfigurationFailsStartup() {
        context.withPropertyValues("spring.profiles.active=infrastructure")
                .run(app -> assertThat(app).hasFailed().getFailure().hasStackTraceContaining("SMTP_TLS_MODE"));
        context.withPropertyValues("spring.profiles.active=infrastructure,delivery-scheduler")
                .run(app -> assertThat(app).hasFailed().getFailure().hasStackTraceContaining("OSS_ENDPOINT"));
    }

    @Test
    void dependencyProbeDoesNotLoadTheDeliveryBeans() {
        context.withPropertyValues("spring.profiles.active=infrastructure,delivery-scheduler,dependency-probe")
                .run(app -> assertThat(app).doesNotHaveBean(FileCleanupLoop.class).doesNotHaveBean(SmtpDelivery.class));
    }
}
