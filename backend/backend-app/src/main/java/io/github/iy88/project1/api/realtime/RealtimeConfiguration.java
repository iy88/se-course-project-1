package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.api.CsrfGuard;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.messaging.DeliverySettings;
import io.github.iy88.project1.messaging.EventReplay;
import io.github.iy88.project1.messaging.EventSignals;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;
import org.springframework.web.socket.server.HandshakeInterceptor;
import tools.jackson.databind.json.JsonMapper;

@Configuration
@EnableWebSocket
@EnableScheduling
@EnableConfigurationProperties(RealtimeSettings.class)
@Profile("infrastructure & !dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class RealtimeConfiguration implements WebSocketConfigurer {
    private final RealtimeSocket socket;
    private final ConnectionQuota quota;
    private final RealtimeAccess access;
    private final CsrfGuard.Origins origins;

    public RealtimeConfiguration(RealtimeAccess access, CsrfGuard.Origins origins, EventReplay events,
                                 EventSignals signals, StringRedisTemplate redis, RealtimeSettings settings,
                                 DeliverySettings delivery, JsonMapper json,
                                 @Value("${project1.redis.namespace}") String namespace) {
        if (origins.allowedOrigins().isEmpty() || settings.replayLimit() > delivery.replayMax()) {
            throw new IllegalArgumentException("Realtime requires configured origins and a valid replay limit");
        }
        this.access = access;
        this.origins = origins;
        quota = new ConnectionQuota(redis, namespace, settings);
        socket = new RealtimeSocket(access, events, signals, quota, settings, json);
    }

    @Bean
    public RealtimeSocket realtimeSocket() { return socket; }

    @Bean
    public OriginConnectionLookup originConnectionLookup() {
        return (session, value) -> {
            if (value == null || value.length() != 36) return Optional.empty();
            UUID candidate;
            try {
                candidate = UUID.fromString(value);
            } catch (IllegalArgumentException invalid) {
                return Optional.empty();
            }
            try {
                return quota.belongsTo(session, candidate) ? Optional.of(candidate) : Optional.empty();
            } catch (DataAccessException unavailable) {
                return Optional.empty();
            }
        };
    }

    @Bean
    public ThreadPoolTaskScheduler realtimeScheduler() {
        var scheduler = new ThreadPoolTaskScheduler();
        scheduler.setThreadNamePrefix("realtime-");
        return scheduler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(socket, "/api/v1/realtime").setAllowedOrigins(origins.allowedOrigins().toArray(String[]::new))
                .addInterceptors(new HandshakeInterceptor() {
                    @Override
                    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                                   WebSocketHandler handler, Map<String, Object> attributes) {
                        var values = request.getHeaders().get("Origin");
                        if (values == null || values.size() != 1 || !origins.allowedOrigins().contains(values.getFirst())) {
                            response.setStatusCode(HttpStatusCode.valueOf(403));
                            return false;
                        }
                        try {
                            var session = access.authenticate(((ServletServerHttpRequest) request).getServletRequest());
                            access.requireCurrent(session);
                            if (!socket.accepting()) {
                                response.setStatusCode(HttpStatusCode.valueOf(503));
                                return false;
                            }
                            attributes.put(RealtimeSocket.IDENTITY, session);
                            return true;
                        } catch (BusinessError failure) {
                            response.setStatusCode(HttpStatusCode.valueOf(failure.status()));
                            return false;
                        } catch (RuntimeException failure) {
                            response.setStatusCode(HttpStatusCode.valueOf(503));
                            return false;
                        }
                    }

                    @Override
                    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                               WebSocketHandler handler, Exception failure) {}
                });
    }
}
