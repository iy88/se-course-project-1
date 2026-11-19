package io.github.iy88.project1.infrastructure;

import java.util.UUID;
import org.springframework.mail.MailException;

class SmtpConnectivityProbe {

    static String send(ExternalProbeProperties.Smtp settings, SmtpProbeRecipient recipient) {
        String probeId = UUID.randomUUID().toString();
        try {
            new SmtpDelivery(settings, 5_000).send(recipient.address(), "[Project1 S1] SMTP probe " + probeId,
                    "Project1 S1 SMTP connectivity probe. ID: " + probeId);
        } catch (MailException exception) {
            throw new IllegalStateException("SMTP probe failed (" + exception.getClass().getSimpleName() + ")");
        }
        return probeId;
    }
}
