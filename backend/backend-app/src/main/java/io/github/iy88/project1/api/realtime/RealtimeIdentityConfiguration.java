package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.SessionGuardRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Binds the realtime channel to the account session created by the identity module. Test slices
 * that already provide a {@link RealtimeSessions} fixture keep their own adapter.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class RealtimeIdentityConfiguration {

    @Bean
    @ConditionalOnMissingBean(RealtimeSessions.class)
    RealtimeSessions accountRealtimeSessions(SessionService sessions, SessionGuardRepository guards,
                                             AccountRepository accounts, AccountSettings settings,
                                             @Value("${project1.config-version}") String configVersion) {
        if (configVersion.isBlank()) throw new IllegalArgumentException("CONFIG_VERSION is required");
        return new AccountRealtimeSessions(sessions, guards, accounts, settings, configVersion);
    }
}
