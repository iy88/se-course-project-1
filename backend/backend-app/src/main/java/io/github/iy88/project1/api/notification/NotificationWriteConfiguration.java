package io.github.iy88.project1.api.notification;

import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.notification.application.NotificationApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Binds the notification read action to the shared write executor.
 *
 * Only the infrastructure profile owns {@link WriteExecutor}, so the binding is
 * declared under the same profile. Without it the read-progress endpoint answers
 * 503 instead of silently writing outside the shared transaction and idempotency
 * scope.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
class NotificationWriteConfiguration {

    @Bean
    NotificationReadCommand notificationReadCommand(WriteExecutor writes, NotificationApplication notifications) {
        return new WriteBackedNotificationReadCommand(writes, notifications);
    }
}
