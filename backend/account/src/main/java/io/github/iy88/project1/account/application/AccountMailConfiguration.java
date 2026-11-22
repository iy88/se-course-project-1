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
        return new AccountMailer(
                environment.getProperty("SMTP_HOST", ""),
                environment.getProperty("SMTP_PORT", Integer.class, 587),
                environment.getProperty("SMTP_TLS_MODE", "starttls"),
                environment.getProperty("SMTP_USERNAME", ""),
                environment.getProperty("SMTP_PASSWORD", ""),
                environment.getProperty("SMTP_FROM", ""));
    }
}
