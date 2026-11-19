package io.github.iy88.project1.infrastructure;

import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSenderImpl;

class SmtpConnectivityProbe {

    static String send(ExternalProbeProperties.Smtp settings, SmtpProbeRecipient recipient) {
        var sender = new JavaMailSenderImpl();
        sender.setHost(settings.host());
        sender.setPort(settings.port());
        sender.setUsername(settings.username());
        sender.setPassword(settings.password());
        sender.setDefaultEncoding(StandardCharsets.UTF_8.name());
        var properties = sender.getJavaMailProperties();
        properties.setProperty("mail.smtp.auth", "true");
        properties.setProperty("mail.smtp.ssl.checkserveridentity", "true");
        properties.setProperty("mail.smtp.connectiontimeout", "5000");
        properties.setProperty("mail.smtp.timeout", "5000");
        properties.setProperty("mail.smtp.writetimeout", "5000");
        boolean startTls = settings.tlsMode() == ExternalProbeProperties.TlsMode.STARTTLS;
        properties.setProperty("mail.smtp.starttls.enable", Boolean.toString(startTls));
        properties.setProperty("mail.smtp.starttls.required", Boolean.toString(startTls));
        properties.setProperty("mail.smtp.ssl.enable", Boolean.toString(!startTls));

        String probeId = UUID.randomUUID().toString();
        var message = new SimpleMailMessage();
        message.setFrom(settings.from());
        message.setTo(recipient.address());
        message.setSubject("[Project1 S1] SMTP probe " + probeId);
        message.setText("Project1 S1 SMTP connectivity probe. ID: " + probeId);
        try {
            sender.send(message);
        } catch (MailException exception) {
            throw new IllegalStateException("SMTP probe failed (" + exception.getClass().getSimpleName() + ")");
        }
        return probeId;
    }
}
