package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.messaging.RealtimeEventSources;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Normal business entry for the infrastructure servlet API. Both business read adapters are
 * required; a missing adapter fails startup instead of silently suppressing its events.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class BusinessRealtimeConfiguration {
    @Bean
    public RealtimeAccess realtimeAccess(RealtimeSessions sessions,
                                         RealtimeEventSources.Notifications notifications,
                                         RealtimeEventSources.Conversations conversations,
                                         List<RealtimeEventSources.SourceAccess> sources) {
        return new BusinessRealtimeAccess(sessions, notifications, conversations, sources);
    }
}
