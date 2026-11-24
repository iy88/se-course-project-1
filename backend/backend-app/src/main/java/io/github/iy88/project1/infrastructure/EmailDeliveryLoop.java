package io.github.iy88.project1.infrastructure;

import io.github.iy88.project1.account.EmailDeliverySettings;
import io.github.iy88.project1.account.application.EmailDeliveryService;
import io.github.iy88.project1.account.application.VerificationMail;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@Profile("delivery-worker & infrastructure & !dependency-probe")
class EmailDeliveryLoop {
    private static final Logger LOG = LoggerFactory.getLogger(EmailDeliveryLoop.class);

    private final EmailDeliveryService deliveries;
    private final VerificationMail mail;
    private final EmailDeliverySettings settings;

    EmailDeliveryLoop(EmailDeliveryService deliveries, VerificationMail mail, EmailDeliverySettings settings) {
        this.deliveries = deliveries;
        this.mail = mail;
        this.settings = settings;
    }

    @Scheduled(fixedDelayString = "${project1.account.email-send-scan-seconds:10}", timeUnit = TimeUnit.SECONDS,
            scheduler = "deliveryScheduler")
    public void deliver() {
        for (EmailDeliveryService.Pending pending : deliveries.claim(settings.emailSendBatchSize(),
                settings.emailSendMaxAttempts(), settings.emailLeaseSeconds())) {
            Instant now = Instant.now();
            long ttl = Math.max(60, Duration.between(now, pending.expiresAt()).toSeconds());
            try {
                mail.sendCode(pending.email(), pending.purpose(), pending.code(), ttl);
                deliveries.markSent(pending.id(), pending.leaseToken(), now);
            } catch (RuntimeException failure) {
                deliveries.markFailed(pending.id(), pending.leaseToken(),
                        now.plusSeconds(settings.emailSendRetrySeconds()), failure.getClass().getSimpleName());
                LOG.warn("email_verification_id={} delivery failed ({})", pending.id(),
                        failure.getClass().getSimpleName());
            }
        }
    }
}
