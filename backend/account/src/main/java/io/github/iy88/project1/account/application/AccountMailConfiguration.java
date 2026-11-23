package io.github.iy88.project1.account.application;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe")
public class AccountMailConfiguration {
    @Bean
    public AccountMailer accountMailer(Environment environment) {
        String host = environment.getProperty("SMTP_HOST", "");
        String username = environment.getProperty("SMTP_USERNAME", "");
        String password = environment.getProperty("SMTP_PASSWORD", "");
        String from = environment.getProperty("SMTP_FROM", "");
        if (host.isBlank() || username.isBlank() || password.isBlank() || from.isBlank()) {
            throw new IllegalArgumentException("SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM are required");
        }
        return new AccountMailer(
                host,
                environment.getProperty("SMTP_PORT", Integer.class, 587),
                environment.getProperty("SMTP_TLS_MODE", "starttls"),
                username,
                password,
                from);
    }
}
