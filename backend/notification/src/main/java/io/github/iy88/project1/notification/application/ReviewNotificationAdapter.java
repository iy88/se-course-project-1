package io.github.iy88.project1.notification.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Adapter for the product-review work package (issue #77).
 *
 * The case module declares the same signature as its {@code ReviewNotifications}
 * port, so binding it in the application assembly is a method reference. The
 * notification is addressed to the seller only, and the audit id is part of the
 * intent key so a retried decision cannot produce a second notice.
 */
public class ReviewNotificationAdapter {
    /** Source type used by the product-review module for one review decision. */
    public static final String SOURCE_TYPE = "product_audit";

    private static final String TEMPLATE_KEY = "product_audit.decision";
    private static final String TEMPLATE_VERSION = "1";

    private final NotificationApplication notifications;

    public ReviewNotificationAdapter(NotificationApplication notifications) {
        this.notifications = notifications;
    }

    /**
     * @param status          the decided review status ({@code passed} or {@code rejected})
     * @param rejectionReason reason shown to the seller; ignored when not rejected
     */
    public void reviewDecided(WriteTransaction transaction, long sellerAccountId, long auditId, long productId,
                              String status, String rejectionReason, Instant occurredAt) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("product_id", Long.toString(productId));
        params.put("decision", status);
        if (rejectionReason != null && !rejectionReason.isBlank()) {
            params.put("reason", rejectionReason);
        }
        var intent = new NotificationIntent(Set.of(sellerAccountId), null, eventType(status),
                new ResourceRef(SOURCE_TYPE, auditId), intentKey(auditId), TEMPLATE_KEY, TEMPLATE_VERSION, params,
                occurredAt);
        notifications.createNotifications(transaction, intent);
    }

    static String eventType(String status) {
        return "rejected".equals(status) ? "product_audit.rejected" : "product_audit.passed";
    }

    static String intentKey(long auditId) {
        return "product_audit.decision:" + auditId;
    }
}
