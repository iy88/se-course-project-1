package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.io.Serial;
import io.github.iy88.project1.messaging.EventReplay;
import io.github.iy88.project1.messaging.EventSignals;
import java.io.IOException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.PongMessage;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

public class RealtimeSocket extends TextWebSocketHandler {
    static final String IDENTITY = RealtimeSocket.class.getName() + ".identity";
    private static final Logger LOG = LoggerFactory.getLogger(RealtimeSocket.class);
    private static final long SEQ_MAX = 9_007_199_254_740_991L;
    private final RealtimeAccess access;
    private final EventReplay events;
    private final EventSignals signals;
    private final ConnectionQuota quota;
    private final RealtimeSettings settings;
    private final JsonMapper json;
    private final Map<String, Connection> connections = new ConcurrentHashMap<>();
    private volatile String redisCursor;
    private long lastHeadPoll;

    RealtimeSocket(RealtimeAccess access, EventReplay events, EventSignals signals, ConnectionQuota quota,
                   RealtimeSettings settings, JsonMapper json) {
        this.access = access;
        this.events = events;
        this.signals = signals;
        this.quota = quota;
        this.settings = settings;
        this.json = json;
    }

    public boolean accepting() { return redisCursor != null; }

    @Override
    public void afterConnectionEstablished(WebSocketSession socket) throws IOException {
        if (!(socket.getAttributes().get(IDENTITY) instanceof RealtimeAccess.Session session)) {
            socket.close(new CloseStatus(4401, "auth_required"));
            return;
        }
        socket.setTextMessageSizeLimit(settings.maxFrameBytes());
        socket.setBinaryMessageSizeLimit(settings.maxFrameBytes());
        connections.put(socket.getId(), new Connection(socket, session));
    }

    @Override
    protected void handleTextMessage(WebSocketSession socket, TextMessage message) {
        var conn = connections.get(socket.getId());
        if (conn == null) return;
        synchronized (conn) {
            try {
                if (message.getPayloadLength() > settings.maxFrameBytes()) throw protocol();
                var frame = json.readTree(message.getPayload());
                var type = frame.path("type").stringValue("");
                if (!conn.active && !"hello".equals(type)) throw protocol();
                access.requireCurrent(conn.session);
                conn.lastInput = System.nanoTime();
                switch (type) {
                    case "hello" -> hello(conn, frame);
                    case "resume" -> resume(conn, cursor(frame));
                    case "ack" -> acknowledge(conn, frame);
                    case "ping" -> send(conn, Map.of("type", "pong", "nonce", nonce(frame)));
                    case "pong" -> pong(conn, frame);
                    default -> throw protocol();
                }
            } catch (BusinessError error) {
                closeBusiness(conn, error);
            } catch (ProtocolError | JacksonException invalid) {
                close(conn, 4400, "protocol_error");
            } catch (IOException | RuntimeException failure) {
                unavailable(conn, failure);
            }
        }
    }

    private void hello(Connection conn, JsonNode frame) throws IOException {
        if (conn.active || !frame.path("protocol_version").isIntegralNumber()
                || !frame.path("protocol_version").canConvertToInt() || frame.path("protocol_version").asInt() != 1
                || !frame.path("csrf_token").isString() || frame.path("csrf_token").stringValue("").isBlank()) {
            throw protocol();
        }
        access.requireHello(conn.session, frame.path("csrf_token").stringValue(""));
        if (!quota.reserve(conn.session, conn.id, false)) {
            close(conn, 4409, "connection_limit");
            return;
        }
        conn.active = true;
        var head = events.head(conn.context());
        var fields = new HashMap<>(EventWire.head(head));
        fields.put("type", "hello_ok");
        fields.put("connection_id", conn.id);
        fields.put("heartbeat_seconds", settings.heartbeatSeconds());
        fields.put("max_frame_bytes", settings.maxFrameBytes());
        send(conn, fields);
        if (!frame.hasNonNull("cursor")) reset(conn);
        else resume(conn, cursor(frame.get("cursor")));
    }

    private void resume(Connection conn, Cursor cursor) throws IOException {
        if (conn.epoch != null) throw protocol();
        conn.epoch = cursor.epoch();
        conn.sent = cursor.after();
        conn.acknowledged = cursor.after();
        pump(conn);
    }

    private void acknowledge(Connection conn, JsonNode frame) throws IOException {
        long sequence = sequence(frame.path("through_seq"));
        if (conn.epoch == null || !conn.epoch.equals(epoch(frame)) || sequence > conn.sent) throw protocol();
        conn.acknowledged = Math.max(conn.acknowledged, sequence);
        if (conn.sent - conn.acknowledged < settings.unacknowledged()) conn.fullSince = 0;
        pump(conn);
    }

    private void pong(Connection conn, JsonNode frame) {
        if (!nonce(frame).equals(conn.pingNonce)) throw protocol();
        conn.pingNonce = null;
    }

    private void pump(Connection conn) throws IOException {
        if (conn.epoch == null) return;
        int room = (int) (settings.unacknowledged() - (conn.sent - conn.acknowledged));
        if (room == 0) return;
        EventReplay.Page page;
        try {
            page = events.replay(conn.context(), conn.epoch, conn.sent, Math.min(room, settings.replayLimit()), access);
        } catch (BusinessError failure) {
            if (!"EVENT_RESYNC_REQUIRED".equals(failure.code())) throw failure;
            reset(conn);
            return;
        }
        for (var frame : page.items()) {
            access.requireCurrent(conn.session);
            send(conn, EventWire.frame(frame));
            conn.sent = switch (frame) {
                case EventReplay.Hint hint -> hint.accountSequence();
                case EventReplay.CursorAdvance advance -> advance.throughSequence();
            };
        }
        if (conn.sent - conn.acknowledged >= settings.unacknowledged()) conn.fullSince = System.nanoTime();
    }

    private void reset(Connection conn) throws IOException {
        conn.epoch = null;
        conn.fullSince = 0;
        var fields = new HashMap<>(EventWire.head(events.head(conn.context())));
        fields.put("type", "sync_reset");
        send(conn, fields);
    }

    @Scheduled(fixedDelay = 1, timeUnit = TimeUnit.SECONDS, scheduler = "realtimeScheduler")
    public void tick() {
        Set<Long> changed = new HashSet<>();
        boolean fullPoll;
        long now = System.nanoTime();
        try {
            String cursor = redisCursor;
            if (cursor == null) {
                redisCursor = signals.tail();
            } else if (!connections.isEmpty()) {
                var hints = signals.readAfter(cursor);
                for (var hint : hints) changed.add(hint.accountId());
                if (!hints.isEmpty()) redisCursor = hints.getLast().offset();
            }
            fullPoll = elapsed(now, lastHeadPoll, settings.headPollSeconds());
            if (fullPoll) lastHeadPoll = now;
        } catch (RuntimeException failure) {
            if (redisCursor != null) LOG.warn("realtime result=redis_unavailable");
            redisCursor = null;
            connections.values().forEach(conn -> {
                synchronized (conn) {
                    close(conn, 4503, "dependency_unavailable");
                }
            });
            return;
        }
        for (var conn : connections.values()) {
            synchronized (conn) {
                try {
                    maintain(conn, now, fullPoll || changed.contains(conn.session.accountId()));
                } catch (BusinessError error) {
                    closeBusiness(conn, error);
                } catch (IOException | RuntimeException failure) {
                    unavailable(conn, failure);
                }
            }
        }
    }

    private void maintain(Connection conn, long now, boolean poll) throws IOException {
        if (!conn.socket.isOpen()) return;
        if (!conn.active) {
            if (elapsed(now, conn.lastInput, settings.helloSeconds())) close(conn, 4400, "hello_timeout");
            return;
        }
        if (elapsed(now, conn.lastInput, settings.idleSeconds())
                || (conn.fullSince != 0 && elapsed(now, conn.fullSince, settings.idleSeconds()))) {
            close(conn, 4400, "connection_timeout");
            return;
        }
        access.requireCurrent(conn.session);
        if (elapsed(now, conn.lastPing, settings.heartbeatSeconds())) {
            if (!quota.reserve(conn.session, conn.id, true)) {
                close(conn, 4409, "connection_limit");
                return;
            }
            conn.lastPing = now;
            if (conn.pingNonce == null) {
                conn.pingNonce = UUID.randomUUID().toString();
                send(conn, Map.of("type", "ping", "nonce", conn.pingNonce));
            }
        }
        if (poll) pump(conn);
    }

    @Override
    protected void handlePongMessage(WebSocketSession socket, PongMessage message) {
        // Application pongs carry the nonce in a text frame.
    }

    @Override
    public void afterConnectionClosed(WebSocketSession socket, CloseStatus status) {
        var removed = connections.remove(socket.getId());
        if (removed == null) return;
        synchronized (removed) {
            release(removed);
        }
    }

    private void closeBusiness(Connection conn, BusinessError error) {
        int status = switch (error.status()) {
            case 401 -> 4401;
            case 403 -> 4403;
            case 429 -> 4409;
            case 503 -> 4503;
            default -> 4400;
        };
        if (status == 4401 || status == 4503) {
            try {
                send(conn, Map.of("type", status == 4401 ? "auth_required" : "dependency_unavailable"));
            } catch (IOException ignored) {
                LOG.debug("connection_id={} result=control_frame_failed", conn.id);
            }
        }
        close(conn, status, status == 4401 ? "auth_required" : "request_failed");
    }

    private void unavailable(Connection conn, Exception failure) {
        LOG.warn("connection_id={} result={}", conn.id, failure.getClass().getSimpleName());
        closeBusiness(conn, new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "服务暂不可用"));
    }

    private void close(Connection conn, int code, String reason) {
        connections.remove(conn.socket.getId(), conn);
        release(conn);
        try {
            if (conn.socket.isOpen()) conn.socket.close(new CloseStatus(code, reason));
        } catch (IOException ignored) {
            LOG.debug("connection_id={} result=close_failed", conn.id);
        }
    }

    private void release(Connection conn) {
        if (!conn.active) return;
        conn.active = false;
        try {
            quota.release(conn.session, conn.id);
        } catch (RuntimeException ignored) {
            LOG.debug("connection_id={} result=lease_release_failed", conn.id);
        }
    }

    private void send(Connection conn, Map<String, Object> frame) throws IOException {
        var message = new TextMessage(json.writeValueAsBytes(frame));
        if (message.getPayloadLength() > settings.maxFrameBytes()) throw new IOException("Event exceeds frame limit");
        conn.socket.sendMessage(message);
    }

    private static Cursor cursor(JsonNode value) {
        return new Cursor(epoch(value), sequence(value.path("after_seq")));
    }

    private static UUID epoch(JsonNode value) {
        String valueText = value.path("epoch").stringValue("");
        if (valueText.length() != 36) throw protocol();
        try {
            return UUID.fromString(valueText);
        } catch (IllegalArgumentException invalid) {
            throw protocol();
        }
    }

    private static long sequence(JsonNode value) {
        if (!value.isIntegralNumber() || !value.canConvertToLong() || value.asLong() < 0 || value.asLong() > SEQ_MAX) {
            throw protocol();
        }
        return value.asLong();
    }

    private static String nonce(JsonNode frame) {
        if (!frame.path("nonce").isString() || frame.path("nonce").stringValue("").length() > 128) throw protocol();
        return frame.path("nonce").stringValue("");
    }

    private static boolean elapsed(long now, long then, int seconds) {
        return now - then >= TimeUnit.SECONDS.toNanos(seconds);
    }

    private static ProtocolError protocol() { return new ProtocolError(); }

    private static final class ProtocolError extends RuntimeException {
        @Serial
        private static final long serialVersionUID = 1L;
    }

    private record Cursor(UUID epoch, long after) {}

    private static final class Connection {
        private final WebSocketSession socket;
        private final RealtimeAccess.Session session;
        private final UUID id = UUID.randomUUID();
        private long lastInput = System.nanoTime();
        private long lastPing = lastInput;
        private long fullSince;
        private String pingNonce;
        private boolean active;
        private UUID epoch;
        private long sent;
        private long acknowledged;

        private Connection(WebSocketSession socket, RealtimeAccess.Session session) {
            this.socket = socket;
            this.session = session;
        }

        private ExecutionContext context() {
            return session.context(UUID.randomUUID(), id);
        }
    }
}
