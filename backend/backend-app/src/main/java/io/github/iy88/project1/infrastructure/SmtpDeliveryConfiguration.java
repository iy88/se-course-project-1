package io.github.iy88.project1.infrastructure;

import io.github.iy88.project1.messaging.DeliverySettings;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !delivery-scheduler & !dependency-probe")
public class SmtpDeliveryConfiguration {
    @Bean
    public SmtpDelivery smtpDelivery(Environment env, DeliverySettings settings) {
        var tls = ExternalProbeProperties.TlsMode.valueOf(
                env.getRequiredProperty("SMTP_TLS_MODE").toUpperCase(java.util.Locale.ROOT));
        var smtp = new ExternalProbeProperties.Smtp(env.getRequiredProperty("SMTP_HOST"),
                env.getRequiredProperty("SMTP_PORT", Integer.class), tls, env.getRequiredProperty("SMTP_USERNAME"),
                env.getRequiredProperty("SMTP_PASSWORD"), env.getRequiredProperty("SMTP_FROM"));
        return new SmtpDelivery(smtp, Math.multiplyExact(settings.ioTimeoutSeconds(), 1000));
    }
}
