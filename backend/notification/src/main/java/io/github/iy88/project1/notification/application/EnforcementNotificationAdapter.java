package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Adapter for the enforcement work package (issue #81).
 *
 * The case module supplies the registry event type (for example
 * {@code case.trade_frozen}), a stable intent key, the case reference and the
 * affected accounts. Dot-separated registry labels are folded onto the shared
 * event-intent naming rule by {@link NotificationIntent#eventIntentType()}.
 */
public class EnforcementNotificationAdapter {
    private static final String TEMPLATE_KEY = "case.enforcement";
    private static final String TEMPLATE_VERSION = "1";

    private final NotificationApplication notifications;

    public EnforcementNotificationAdapter(NotificationApplication notifications) {
        this.notifications = notifications;
    }

    public void create(WriteTransaction transaction, String eventType, String intentKey, ResourceRef source,
                       Set<Long> recipients, String reason, Instant occurredAt) {
        Map<String, String> params = new LinkedHashMap<>();
        if (reason != null && !reason.isBlank()) {
            params.put("reason", reason);
        }
        var intent = new NotificationIntent(recipients, null, eventType, source, intentKey, TEMPLATE_KEY,
                TEMPLATE_VERSION, params, occurredAt);
        notifications.createNotifications(transaction, intent);
    }
}
