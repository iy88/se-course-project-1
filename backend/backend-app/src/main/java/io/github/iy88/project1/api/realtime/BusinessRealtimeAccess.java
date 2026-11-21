package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import io.github.iy88.project1.messaging.UserEvents;
import jakarta.servlet.http.HttpServletRequest;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * Business projection shared by the WebSocket transport and the HTTP recovery endpoints.
 * It delegates Session, CSRF, notification and conversation ownership to their owning modules.
 */
public final class BusinessRealtimeAccess implements RealtimeAccess {
    private static final int SCHEMA_VERSION = 1;
    private static final String NOTIFICATION = "notification";

    private final RealtimeSessions sessions;
    private final RealtimeEventSources.Notifications notifications;
    private final RealtimeEventSources.Conversations conversations;
    private final Map<String, RealtimeEventSources.SourceAccess> sources;

    public BusinessRealtimeAccess(RealtimeSessions sessions,
                                  RealtimeEventSources.Notifications notifications,
                                  RealtimeEventSources.Conversations conversations,
                                  List<RealtimeEventSources.SourceAccess> sourceAccess) {
        this.sessions = Objects.requireNonNull(sessions, "RealtimeSessions adapter is required");
        this.notifications = Objects.requireNonNull(notifications, "Notifications adapter is required");
        this.conversations = Objects.requireNonNull(conversations, "Conversations adapter is required");
        var registered = new HashMap<String, RealtimeEventSources.SourceAccess>();
        for (var access : sourceAccess) {
            if (registered.putIfAbsent(access.sourceType(), access) != null) {
                throw new IllegalArgumentException("Duplicate source access: " + access.sourceType());
            }
        }
        sources = Map.copyOf(registered);
    }

    @Override
    public Session authenticate(HttpServletRequest request) {
        return sessions.resolve(request).orElseThrow(BusinessRealtimeAccess::authenticationRequired);
    }

    @Override
    public void requireCurrent(Session session) {
        sessions.requireCurrent(session);
    }

    @Override
    public void requireHello(Session session, String csrfToken) {
        sessions.requireCsrf(session, csrfToken);
    }

    @Override
    public Optional<Map<String, ?>> project(ExecutionContext context, UserEvents.Event event) {
        if (event.schemaVersion() != SCHEMA_VERSION) return Optional.empty();
        return switch (event.type()) {
            case "notification_created" -> notification(context, event, false);
            case "notification_read" -> notification(context, event, true);
            case "message_created" -> messageCreated(context, event);
            case "message_read" -> messageRead(context, event);
            case "conversation_archived" -> conversationArchived(context, event);
            case "source_changed" -> sourceChanged(context, event);
            default -> Optional.empty();
        };
    }

    private Optional<Map<String, ?>> notification(ExecutionContext context, UserEvents.Event event, boolean read) {
        var notificationId = notificationId(event);
        if (notificationId.isEmpty()) return Optional.empty();
        var hint = notifications.read(context, notificationId.get());
        if (hint.isEmpty()) return Optional.empty();
        var data = new LinkedHashMap<String, Object>();
        data.put("notification_id", Long.toString(notificationId.get()));
        if (read) {
            // The notification owns the first authoritative read time; never reuse transport time.
            if (hint.get().readAt() == null) return Optional.empty();
            data.put("read_at", hint.get().readAt());
        }
        return Optional.of(Map.copyOf(data));
    }

    private Optional<Map<String, ?>> messageCreated(ExecutionContext context, UserEvents.Event event) {
        var conversation = conversation(event.source());
        var message = event.payload();
        if (conversation.isEmpty() || message == null
                || !conversation.get().kind().messageType().equals(message.type())) {
            return Optional.empty();
        }
        var hint = conversations.readMessage(context, conversation.get(), message.id());
        if (hint.isEmpty()) return Optional.empty();
        var data = conversationData(conversation.get());
        data.put("message_id", Long.toString(message.id()));
        data.put("message_seq", hint.get().sequence());
        if (hint.get().businessEventId() != null) data.put("business_event_id", hint.get().businessEventId());
        return Optional.of(Map.copyOf(data));
    }

    private Optional<Map<String, ?>> messageRead(ExecutionContext context, UserEvents.Event event) {
        var conversation = conversation(event.source());
        if (conversation.isEmpty() || event.sourceSequence() == null) return Optional.empty();
        if (!conversations.canRead(context, conversation.get())) return Optional.empty();
        var data = conversationData(conversation.get());
        data.put("last_read_seq", event.sourceSequence());
        return Optional.of(Map.copyOf(data));
    }

    private Optional<Map<String, ?>> conversationArchived(ExecutionContext context, UserEvents.Event event) {
        var conversation = conversation(event.source());
        if (conversation.isEmpty() || !conversations.canRead(context, conversation.get())) return Optional.empty();
        return Optional.of(Map.copyOf(conversationData(conversation.get())));
    }

    private Optional<Map<String, ?>> sourceChanged(ExecutionContext context, UserEvents.Event event) {
        var access = sources.get(event.source().type());
        if (access == null || !access.canRead(context, event.source())) return Optional.empty();
        var data = new LinkedHashMap<String, Object>();
        data.put("source_type", event.source().type());
        data.put("source_id", Long.toString(event.source().id()));
        return Optional.of(Map.copyOf(data));
    }

    private static Optional<Long> notificationId(UserEvents.Event event) {
        if (NOTIFICATION.equals(event.source().type())) return Optional.of(event.source().id());
        ResourceRef payload = event.payload();
        if (payload != null && NOTIFICATION.equals(payload.type())) return Optional.of(payload.id());
        return Optional.empty();
    }

    private static Optional<RealtimeEventSources.ConversationRef> conversation(ResourceRef source) {
        for (var kind : RealtimeEventSources.ConversationKind.values()) {
            if (kind.sourceType().equals(source.type())) {
                return Optional.of(new RealtimeEventSources.ConversationRef(kind, source.id()));
            }
        }
        return Optional.empty();
    }

    private static LinkedHashMap<String, Object> conversationData(RealtimeEventSources.ConversationRef conversation) {
        var data = new LinkedHashMap<String, Object>();
        data.put("conversation_kind", conversation.kind().wireName());
        data.put("conversation_id", Long.toString(conversation.id()));
        return data;
    }

    private static BusinessError authenticationRequired() {
        return new BusinessError("AUTHENTICATION_REQUIRED", 401, "请登录");
    }
}
