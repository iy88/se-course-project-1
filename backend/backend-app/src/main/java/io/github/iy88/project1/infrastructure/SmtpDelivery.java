package io.github.iy88.project1.infrastructure;

import java.nio.charset.StandardCharsets;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.transaction.support.TransactionSynchronizationManager;

public final class SmtpDelivery {
    private final JavaMailSenderImpl sender;
    private final String from;

    SmtpDelivery(ExternalProbeProperties.Smtp settings, int timeoutMillis) {
        var sender = new JavaMailSenderImpl();
        sender.setHost(settings.host());
        sender.setPort(settings.port());
        sender.setUsername(settings.username());
        sender.setPassword(settings.password());
        sender.setDefaultEncoding(StandardCharsets.UTF_8.name());
        var properties = sender.getJavaMailProperties();
        properties.setProperty("mail.smtp.auth", "true");
        properties.setProperty("mail.smtp.ssl.checkserveridentity", "true");
        properties.setProperty("mail.smtp.connectiontimeout", Integer.toString(timeoutMillis));
        properties.setProperty("mail.smtp.timeout", Integer.toString(timeoutMillis));
        properties.setProperty("mail.smtp.writetimeout", Integer.toString(timeoutMillis));
        boolean startTls = settings.tlsMode() == ExternalProbeProperties.TlsMode.STARTTLS;
        properties.setProperty("mail.smtp.starttls.enable", Boolean.toString(startTls));
        properties.setProperty("mail.smtp.starttls.required", Boolean.toString(startTls));
        properties.setProperty("mail.smtp.ssl.enable", Boolean.toString(!startTls));

        this.sender = sender;
        this.from = settings.from();
    }

    public void send(String recipient, String subject, String body) {
        if (TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("SMTP delivery requires a committed work lease");
        }
        var message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(recipient);
        message.setSubject(subject);
        message.setText(body);
        sender.send(message);
    }
}
