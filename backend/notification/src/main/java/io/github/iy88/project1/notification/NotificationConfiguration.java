package io.github.iy88.project1.notification;

import io.github.iy88.project1.notification.application.EnforcementNotificationAdapter;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationQueries;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.notification.application.ReviewNotificationAdapter;
import io.github.iy88.project1.notification.persistence.NotificationStore;
import java.time.Clock;
import java.util.Optional;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Lazy;

/**
 * Wires the notification module onto the shared primitives.
 *
 * Lazy: the persistence bean needs a data source, and the probe-only application
 * context deliberately runs without one. Nothing here is created until a caller
 * actually asks for it, so a context without JPA still starts.
 *
 * The source projection port stays optional: without it the query side answers
 * with the approved public hint and hides the jump target, which is exactly the
 * contract behaviour for a source the reader may not open.
 */
@Lazy
@Configuration(proxyBeanMethods = false)
public class NotificationConfiguration {

    @Bean
    NotificationApplication notificationApplication(NotificationStore store, ObjectProvider<Clock> clock) {
        return new NotificationApplication(store, clock.getIfAvailable(() -> Clock.systemUTC()));
    }

    @Bean
    NotificationQueries notificationQueries(NotificationStore store,
                                            ObjectProvider<NotificationSourcePort> sources) {
        var projections = sources.orderedStream().toList();
        NotificationSourcePort composite = (context, facts) -> projections.stream()
                .flatMap(projection -> projection.project(context, facts).stream())
                .findFirst();
        return new NotificationQueries(store, Optional.of(composite));
    }

    @Bean
    ReviewNotificationAdapter reviewNotificationAdapter(NotificationApplication notifications) {
        return new ReviewNotificationAdapter(notifications);
    }

    @Bean
    EnforcementNotificationAdapter enforcementNotificationAdapter(NotificationApplication notifications) {
        return new EnforcementNotificationAdapter(notifications);
    }
}
