package io.github.iy88.project1.account.application;

import io.github.iy88.project1.core.BusinessError;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSenderImpl;

public class AccountMailer {
    private final JavaMailSenderImpl sender;
    private final String from;

    public AccountMailer(String host, int port, String tlsMode, String username, String password, String from) {
        if (host == null || host.isBlank() || username == null || username.isBlank() || password == null
                || password.isBlank() || from == null || from.isBlank()) {
            this.sender = null;
            this.from = null;
            return;
        }
        var configured = new JavaMailSenderImpl();
        configured.setHost(host);
        configured.setPort(port);
        configured.setUsername(username);
        configured.setPassword(password);
        configured.setDefaultEncoding(StandardCharsets.UTF_8.name());
        var properties = configured.getJavaMailProperties();
        properties.setProperty("mail.smtp.auth", "true");
        properties.setProperty("mail.smtp.ssl.checkserveridentity", "true");
        properties.setProperty("mail.smtp.connectiontimeout", "10000");
        properties.setProperty("mail.smtp.timeout", "10000");
        properties.setProperty("mail.smtp.writetimeout", "10000");
        boolean startTls = !"ssl".equals(tlsMode.toLowerCase(Locale.ROOT));
        properties.setProperty("mail.smtp.starttls.enable", Boolean.toString(startTls));
        properties.setProperty("mail.smtp.starttls.required", Boolean.toString(startTls));
        properties.setProperty("mail.smtp.ssl.enable", Boolean.toString(!startTls));
        this.sender = configured;
        this.from = from;
    }

    public void sendCode(String recipient, String code, long ttlSeconds) {
        if (sender == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "邮件服务未配置");
        }
        var message = new SimpleMailMessage();
        message.setFrom(from);
        message.setTo(recipient);
        message.setSubject("Project1 验证码");
        message.setText("你的验证码是 " + code + "，" + Math.max(1, ttlSeconds / 60) + " 分钟内有效。");
        sender.send(message);
    }
}
