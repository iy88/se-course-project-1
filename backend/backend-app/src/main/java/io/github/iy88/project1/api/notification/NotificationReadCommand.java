package io.github.iy88.project1.api.notification;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteResult;
import tools.jackson.databind.JsonNode;

/**
 * Marks one notification as read through the shared write use case.
 *
 * Kept as a narrow port so the controller stays testable without the write
 * orchestration, and so the idempotency and lock handling lives in one adapter.
 */
@FunctionalInterface
public interface NotificationReadCommand {
    WriteResult<JsonNode> markRead(ExecutionContext context, String idempotencyKey, long notificationId);
}
