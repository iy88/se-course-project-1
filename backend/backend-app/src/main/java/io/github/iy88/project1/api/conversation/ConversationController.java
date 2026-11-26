package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.conversation.ConversationKind;
import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.application.ConversationQueries;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteResult;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Conversation endpoints API-CONV-001—005.
 *
 * Identity always comes from the session adapter. Reads run against the query side and never
 * advance read progress; writes go through the shared write executor with an Idempotency-Key.
 * Case threads belong to the case module (#84, S4); until that adapter is wired this controller
 * answers 503 for {@code kind=case} instead of pretending the thread is missing.
 */
@RestController
@RequestMapping("/api/v1/conversations")
@Profile("!dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class ConversationController {
    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";
    private static final int DEFAULT_PAGE = 1;
    private static final int DEFAULT_PAGE_SIZE = 20;
    private static final int DEFAULT_LIMIT = 20;

    private final ObjectProvider<ConversationQueries> queries;
    private final ObjectProvider<ConversationWriteCommands> commands;
    private final ObjectProvider<ConversationActorResolver> actors;
    private final ApiRequestContext requests;
    private final ConversationSettings settings;

    public ConversationController(ObjectProvider<ConversationQueries> queries,
                                  ObjectProvider<ConversationWriteCommands> commands,
                                  ObjectProvider<ConversationActorResolver> actors,
                                  ApiRequestContext requests,
                                  ConversationSettings settings) {
        this.queries = queries;
        this.commands = commands;
        this.actors = actors;
        this.requests = requests;
        this.settings = settings;
    }

    @GetMapping
    public ResponseEntity<Map<String, Object>> list(HttpServletRequest request,
                                                    @RequestParam(required = false) Integer page,
                                                    @RequestParam(name = "page_size", required = false)
                                                    Integer pageSize) {
        var context = context(request);
        int currentPage = positive(page, DEFAULT_PAGE, "page");
        int size = pageSize(pageSize, "page_size");
        return ok(ConversationWire.page(queries().list(context, currentPage, size)));
    }

    @GetMapping("/{conversation_kind}/{conversation_id}/messages")
    public ResponseEntity<Map<String, Object>> messages(
            HttpServletRequest request,
            @PathVariable("conversation_kind") String kindValue,
            @PathVariable("conversation_id") String conversationId,
            @RequestParam(name = "after_seq", required = false) Long afterSeq,
            @RequestParam(name = "before_seq", required = false) Long beforeSeq,
            @RequestParam(required = false) Integer limit) {
        var context = context(request);
        var kind = kind(kindValue);
        requireSupported(kind);
        long id = identifier(conversationId);
        int size = positive(limit, DEFAULT_LIMIT, "limit");
        if (size > settings.getMaxPageSize()) {
            throw new BusinessError("INPUT_INVALID", 422, "limit 超出上限");
        }
        var page = switch (kind) {
            case CHAT -> queries().pageChat(context, id, beforeSeq, afterSeq, size);
            case TRADE -> queries().pageTrade(context, id, beforeSeq, afterSeq, size);
            case CASE -> throw unsupportedKind();
        };
        return ok(ConversationWire.messagePage(page, kind));
    }

    @PostMapping("/private")
    public ResponseEntity<Object> startPrivate(
            HttpServletRequest request,
            @RequestBody(required = false) ConversationRequests.PrivateChat body,
            @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String idempotencyKey) {
        var context = context(request);
        var key = idempotencyKey(idempotencyKey);
        long target = accountId(body == null ? null : body.targetAccountId());
        return write(commands().startPrivate(context, key, target));
    }

    @PostMapping("/{conversation_kind}/{conversation_id}/messages")
    public ResponseEntity<Object> send(
            HttpServletRequest request,
            @PathVariable("conversation_kind") String kindValue,
            @PathVariable("conversation_id") String conversationId,
            @RequestBody(required = false) ConversationRequests.Send body,
            @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String idempotencyKey) {
        var context = context(request);
        var kind = kind(kindValue);
        requireSupported(kind);
        long id = identifier(conversationId);
        var key = idempotencyKey(idempotencyKey);
        if (body == null || body.body() == null || body.body().isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "消息内容不能为空");
        }
        return write(commands().send(context, key, kind, id, body.body()));
    }

    @PostMapping("/{conversation_kind}/{conversation_id}/read-progress")
    public ResponseEntity<Object> markRead(
            HttpServletRequest request,
            @PathVariable("conversation_kind") String kindValue,
            @PathVariable("conversation_id") String conversationId,
            @RequestBody(required = false) ConversationRequests.Read body,
            @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String idempotencyKey) {
        var context = context(request);
        var kind = kind(kindValue);
        requireSupported(kind);
        long id = identifier(conversationId);
        var key = idempotencyKey(idempotencyKey);
        Long displayed = body == null ? null : body.displayedSeq();
        if (displayed == null || displayed < 0) {
            throw new BusinessError("INPUT_INVALID", 422, "displayed_seq 取值无效");
        }
        return write(commands().markRead(context, key, kind, id, displayed));
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

    private ConversationQueries queries() {
        var available = queries.getIfAvailable();
        if (available == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "会话查询暂不可用");
        }
        return available;
    }

    private ConversationWriteCommands commands() {
        var available = commands.getIfAvailable();
        if (available == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "会话写入暂不可用");
        }
        return available;
    }

    private static ResponseEntity<Object> write(WriteResult<?> result) {
        return ResponseEntity.status(result.status()).cacheControl(CacheControl.noStore()).body(result.data());
    }

    private static ResponseEntity<Map<String, Object>> ok(Map<String, Object> body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }

    private static ConversationKind kind(String value) {
        for (ConversationKind kind : ConversationKind.values()) {
            if (kind.wireValue().equals(value)) {
                return kind;
            }
        }
        throw new BusinessError("INPUT_INVALID", 422, "conversation_kind 取值无效");
    }

    private static void requireSupported(ConversationKind kind) {
        if (kind == ConversationKind.CASE) {
            throw unsupportedKind();
        }
    }

    private static BusinessError unsupportedKind() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "事项会话由事项模块提供");
    }

    private static long identifier(String value) {
        try {
            long id = Long.parseLong(value);
            if (id <= 0) throw new NumberFormatException();
            return id;
        } catch (NumberFormatException invalid) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "会话不存在");
        }
    }

    private static long accountId(String value) {
        if (value == null) {
            throw new BusinessError("INPUT_INVALID", 422, "target_account_id 取值无效");
        }
        try {
            long id = Long.parseLong(value);
            if (id <= 0) throw new NumberFormatException();
            return id;
        } catch (NumberFormatException invalid) {
            throw new BusinessError("INPUT_INVALID", 422, "target_account_id 取值无效");
        }
    }

    private static String idempotencyKey(String value) {
        if (value == null || value.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "缺少 Idempotency-Key");
        }
        return value;
    }

    private static int positive(Integer value, int fallback, String field) {
        if (value == null) return fallback;
        if (value < 1) throw new BusinessError("INPUT_INVALID", 422, field + " 取值无效");
        return value;
    }

    private int pageSize(Integer value, String field) {
        if (value == null) return DEFAULT_PAGE_SIZE;
        if (value < 1 || value > settings.getMaxPageSize()) {
            throw new BusinessError("INPUT_INVALID", 422, field + " 取值无效");
        }
        return value;
    }
}
