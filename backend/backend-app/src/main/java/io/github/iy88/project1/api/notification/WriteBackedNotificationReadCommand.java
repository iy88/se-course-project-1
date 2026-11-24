package io.github.iy88.project1.api.notification;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.application.NotificationApplication;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Binds the notification read action onto the shared write use case.
 *
 * The use case owns one transaction and one idempotency scope, declares the
 * notification row in its lock plan and locks it inside the transaction, so a
 * repeated request replays the first result instead of registering a second read.
 */
public class WriteBackedNotificationReadCommand implements NotificationReadCommand {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String OPERATION = "notification.mark_read";
    private static final String RESOURCE_TYPE = "notification";

    private final WriteExecutor writes;
    private final NotificationApplication notifications;

    public WriteBackedNotificationReadCommand(WriteExecutor writes, NotificationApplication notifications) {
        this.writes = writes;
        this.notifications = notifications;
    }

    @Override
    public WriteResult<JsonNode> markRead(ExecutionContext context, String idempotencyKey, long notificationId) {
        long accountId = Long.parseLong(context.actorId());
        return writes.run(context, OPERATION, idempotencyKey, notificationId, new UseCase(notifications, accountId));
    }

    private record UseCase(NotificationApplication notifications, long accountId)
            implements WriteExecutor.UseCase<Long, Long> {
        @Override
        public JsonNode digestInput(Long request) {
            var node = JSON.createObjectNode();
            node.put("notification_id", Long.toString(request));
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, Long request) {
            return new LockPlan(Map.of(), Set.of(new LockPlan.Key(LockPlan.Domain.NOTIFICATION, List.of(request))));
        }

        @Override
        public Long qualify(ExecutionContext context, Long request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, Long qualification, ResourceRef resource) {
            if (!RESOURCE_TYPE.equals(resource.type()) || resource.id() != qualification) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "通知不存在");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, Long request, Long qualification,
                                             LockPlan plan) {
            var item = notifications.markRead(transaction, accountId, request);
            return new WriteResult.Response<>(200, NotificationWire.item(item),
                    new ResourceRef(RESOURCE_TYPE, request));
        }
    }
}
