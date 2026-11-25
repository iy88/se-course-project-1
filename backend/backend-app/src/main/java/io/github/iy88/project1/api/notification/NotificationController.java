package io.github.iy88.project1.api.notification;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.notification.application.NotificationQuery;
import io.github.iy88.project1.notification.application.NotificationQueries;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Read and read-progress entry points of the in-site notification centre
 * (API-COM-NOTIFY-002—004).
 *
 * Identity comes from the session adapter, never from the caller. The endpoints
 * answer 503 while a dependency is not wired yet (no database, no identity
 * adapter) rather than pretending success, and reading a list or one entry never
 * advances the read state — only the explicit read-progress call does.
 */
@RestController
@RequestMapping("/api/v1/account/notifications")
@Profile("!dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class NotificationController {
    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";

    private final ObjectProvider<NotificationQueries> queries;
    private final ObjectProvider<NotificationReadCommand> reads;
    private final ObjectProvider<NotificationActorResolver> actors;
    private final ApiRequestContext requests;

    public NotificationController(ObjectProvider<NotificationQueries> queries,
                                  ObjectProvider<NotificationReadCommand> reads,
                                  ObjectProvider<NotificationActorResolver> actors,
                                  ApiRequestContext requests) {
        this.queries = queries;
        this.reads = reads;
        this.actors = actors;
        this.requests = requests;
    }

    @GetMapping
    public ResponseEntity<Map<String, Object>> list(HttpServletRequest request,
                                                    @RequestParam(required = false) Integer page,
                                                    @RequestParam(name = "page_size", required = false) Integer pageSize,
                                                    @RequestParam(required = false) String read,
                                                    @RequestParam(name = "event_type", required = false)
                                                    String eventType) {
        var context = context(request);
        var query = new NotificationQuery(positive(page, 1, "page"), pageSize(pageSize), filter(read), eventType);
        var body = NotificationWire.page(queries().list(context, query));
        return ok(body);
    }

    @GetMapping("/{notification_id}")
    public ResponseEntity<Map<String, Object>> get(HttpServletRequest request,
                                                    @PathVariable("notification_id") String notificationId) {
        var context = context(request);
        var body = NotificationWire.detail(queries().get(context, identifier(notificationId)));
        return ok(body);
    }

    @PutMapping("/{notification_id}/read")
    public ResponseEntity<Object> markRead(
            HttpServletRequest request,
            @PathVariable("notification_id") String notificationId,
            @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String idempotencyKey) {
        var context = context(request);
        long id = identifier(notificationId);
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "缺少 Idempotency-Key");
        }
        var command = reads.getIfAvailable();
        if (command == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "通知写入暂不可用");
        }
        var result = command.markRead(context, idempotencyKey, id);
        // The stored result is already the response body, so a replay answers with
        // exactly the payload of the first successful call.
        return ResponseEntity.status(result.status()).cacheControl(CacheControl.noStore()).body(result.data());
    }

    private ExecutionContext context(HttpServletRequest request) {
        var resolver = actors.getIfAvailable();
        if (resolver == null) {
            throw new BusinessError("AUTHENTICATION_UNAVAILABLE", 503, "身份服务暂不可用");
        }
        var actor = resolver.resolve(request);
        return requests.forActor(request, ExecutionContext.ActorKind.ACCOUNT, Long.toString(actor.accountId()),
                actor.sessionId(), null, actor.credentialVersion());
    }

    private NotificationQueries queries() {
        var available = queries.getIfAvailable();
        if (available == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "通知查询暂不可用");
        }
        return available;
    }

    private static ResponseEntity<Map<String, Object>> ok(Map<String, Object> body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }

    private static NotificationQuery.ReadFilter filter(String read) {
        if (read == null || read.isBlank() || "all".equals(read)) return NotificationQuery.ReadFilter.ALL;
        return switch (read) {
            case "unread" -> NotificationQuery.ReadFilter.UNREAD;
            case "read" -> NotificationQuery.ReadFilter.READ;
            default -> throw new BusinessError("INPUT_INVALID", 422, "read 取值无效");
        };
    }

    private static int positive(Integer value, int fallback, String field) {
        if (value == null) return fallback;
        if (value < 1) throw new BusinessError("INPUT_INVALID", 422, field + " 取值无效");
        return value;
    }

    private static int pageSize(Integer value) {
        if (value == null) return NotificationQuery.DEFAULT_PAGE_SIZE;
        if (value < 1 || value > NotificationQuery.MAX_PAGE_SIZE) {
            throw new BusinessError("INPUT_INVALID", 422, "page_size 取值无效");
        }
        return value;
    }

    private static long identifier(String value) {
        try {
            long id = Long.parseLong(value);
            if (id <= 0) throw new NumberFormatException();
            return id;
        } catch (NumberFormatException invalid) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "通知不存在");
        }
    }
}
