package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.messaging.EventReplay;
import io.github.iy88.project1.messaging.EventSignals;
import io.github.iy88.project1.messaging.UserEvents;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class RealtimeSocketTests {
    private final JsonMapper json = JsonMapper.builder().build();
    private final RealtimeAccess access = mock(RealtimeAccess.class);
    private final EventReplay events = mock(EventReplay.class);
    private final EventSignals signals = mock(EventSignals.class);
    private final ConnectionQuota quota = mock(ConnectionQuota.class);
    private final WebSocketSession socket = mock(WebSocketSession.class);
    private final RealtimeAccess.Session session = new RealtimeAccess.Session(14, UUID.randomUUID(), 1, "test");
    private final UUID epoch = UUID.randomUUID();
    private final List<JsonNode> frames = new ArrayList<>();
    private final RealtimeSocket handler = new RealtimeSocket(access, events, signals, quota,
            new RealtimeSettings(2, 10, 4, 2, 5, 10, 30, 1024, 2), json);

    @BeforeEach
    void connect() throws Exception {
        when(socket.getId()).thenReturn("test-socket");
        when(socket.getAttributes()).thenReturn(Map.of(RealtimeSocket.IDENTITY, session));
        when(socket.isOpen()).thenReturn(true);
        when(quota.reserve(eq(session), any(UUID.class), eq(false))).thenReturn(true);
        when(events.head(any(ExecutionContext.class))).thenReturn(new UserEvents.Head(epoch, 3, 0));
        doAnswer(invocation -> {
            TextMessage message = invocation.getArgument(0);
            frames.add(json.readTree(message.getPayload()));
            return null;
        }).when(socket).sendMessage(any(TextMessage.class));
        handler.afterConnectionEstablished(socket);
    }

    @Test
    void resumesForTheAuthenticatedAccountAndWaitsForAckWhenTheWindowIsFull() {
        when(events.replay(any(ExecutionContext.class), eq(epoch), eq(0L), eq(2), eq(access)))
                .thenReturn(new EventReplay.Page(List.of(new EventReplay.CursorAdvance(epoch, 1, 2)), 2, 3, true));
        when(events.replay(any(ExecutionContext.class), eq(epoch), eq(2L), eq(1), eq(access)))
                .thenReturn(new EventReplay.Page(List.of(new EventReplay.CursorAdvance(epoch, 3, 3)), 3, 3, false));

        send(hello(epoch, 0));
        UUID connectionId = UUID.fromString(frames.getFirst().path("connection_id").asString());
        assertThat(types()).containsExactly("hello_ok", "cursor_advance");
        assertThat(frames.getLast().path("through_seq").asLong()).isEqualTo(2);
        verify(access).requireHello(session, "token");
        verify(events).replay(argThat(context -> context.actorId().equals("14")
                && session.id().equals(context.sessionId()) && connectionId.equals(context.originConnectionId())),
                eq(epoch), eq(0L), eq(2), eq(access));
        verify(events, never()).replay(any(ExecutionContext.class), eq(epoch), eq(2L), eq(1), eq(access));

        send("""
                {"type":"ack","epoch":"%s","through_seq":1}
                """.formatted(epoch));

        assertThat(types()).containsExactly("hello_ok", "cursor_advance", "cursor_advance");
        assertThat(frames.getLast().path("through_seq").asLong()).isEqualTo(3);
    }

    @Test
    void redisWakeImmediatelyPumpsOnlyTheMatchingAccount() {
        when(events.replay(any(ExecutionContext.class), eq(epoch), eq(0L), eq(2), eq(access)))
                .thenReturn(new EventReplay.Page(List.of(), 0, 0, false))
                .thenReturn(new EventReplay.Page(List.of(new EventReplay.CursorAdvance(epoch, 1, 1)), 1, 1, false));
        send(hello(epoch, 0));

        handler.wakeAccount(15);
        assertThat(types()).containsExactly("hello_ok");

        handler.wakeAccount(14);
        assertThat(types()).containsExactly("hello_ok", "cursor_advance");
        assertThat(frames.getLast().path("through_seq").asLong()).isEqualTo(1);
        verifyNoInteractions(signals);
    }

    @Test
    void staleCursorRequestsResetAndAcceptsResumeAfterSnapshots() {
        UUID staleEpoch = UUID.randomUUID();
        when(events.replay(any(ExecutionContext.class), eq(staleEpoch), eq(0L), eq(2), eq(access)))
                .thenThrow(new BusinessError("EVENT_RESYNC_REQUIRED", 409, "stale cursor"));
        when(events.replay(any(ExecutionContext.class), eq(epoch), eq(3L), eq(2), eq(access)))
                .thenReturn(new EventReplay.Page(List.of(), 3, 3, false));

        send(hello(staleEpoch, 0));
        assertThat(types()).containsExactly("hello_ok", "sync_reset");
        assertThat(frames.getLast().path("epoch").asString()).isEqualTo(epoch.toString());
        assertThat(frames.getLast().path("head_seq").asLong()).isEqualTo(3);

        send("""
                {"type":"resume","epoch":"%s","after_seq":3}
                """.formatted(epoch));

        verify(events).replay(any(ExecutionContext.class), eq(epoch), eq(3L), eq(2), eq(access));
        assertThat(types()).containsExactly("hello_ok", "sync_reset");
    }

    @Test
    void ackBeyondTheLastSentSequenceClosesAndReleasesQuota() throws Exception {
        when(events.replay(any(ExecutionContext.class), eq(epoch), eq(0L), eq(2), eq(access)))
                .thenReturn(new EventReplay.Page(List.of(), 0, 3, false));
        send(hello(epoch, 0));
        UUID connectionId = UUID.fromString(frames.getFirst().path("connection_id").asString());

        send("""
                {"type":"ack","epoch":"%s","through_seq":1}
                """.formatted(epoch));
        handler.afterConnectionClosed(socket, CloseStatus.NORMAL);

        verify(socket).close(new CloseStatus(4400, "protocol_error"));
        verify(quota).release(session, connectionId);
        assertThat(types()).containsExactly("hello_ok");
    }

    @Test
    void rejectsBusinessFramesBeforeHello() throws Exception {
        send("""
                {"type":"ping","nonce":"early"}
                """);

        verify(socket).close(new CloseStatus(4400, "protocol_error"));
        verifyNoInteractions(access, quota, events);
        assertThat(frames).isEmpty();
    }

    @Test
    void revokedSessionCannotResumeOrReserveQuota() throws Exception {
        doThrow(new BusinessError("AUTHENTICATION_REQUIRED", 401, "expired"))
                .when(access).requireCurrent(session);

        send(hello(epoch, 0));

        assertThat(types()).containsExactly("auth_required");
        verify(socket).close(new CloseStatus(4401, "auth_required"));
        verifyNoInteractions(quota, events);
    }

    @Test
    void rejectsHelloWhenConnectionQuotaIsFull() throws Exception {
        when(quota.reserve(eq(session), any(UUID.class), eq(false))).thenReturn(false);

        send(hello(epoch, 0));

        verify(socket).close(new CloseStatus(4409, "connection_limit"));
        verify(quota, never()).release(eq(session), any(UUID.class));
        verifyNoInteractions(events);
        assertThat(frames).isEmpty();
    }

    @Test
    void redisFailureClosesConnectionsUntilTheSignalCursorIsReinitialized() throws Exception {
        when(signals.tail()).thenReturn("4-0");
        handler.tick();
        assertThat(handler.accepting()).isTrue();
        send("""
                {"type":"hello","protocol_version":1,"csrf_token":"token"}
                """);
        UUID connectionId = UUID.fromString(frames.getFirst().path("connection_id").asString());
        when(signals.readAfter("4-0")).thenThrow(new IllegalStateException("Redis unavailable"));

        handler.tick();

        assertThat(handler.accepting()).isFalse();
        verify(socket).close(new CloseStatus(4503, "dependency_unavailable"));
        verify(quota).release(session, connectionId);
        assertThat(types()).containsExactly("hello_ok", "sync_reset");

        handler.tick();
        assertThat(handler.accepting()).isTrue();
    }

    private void send(String payload) {
        handler.handleTextMessage(socket, new TextMessage(payload));
    }

    private List<String> types() {
        return frames.stream().map(frame -> frame.path("type").asString()).toList();
    }

    private static String hello(UUID epoch, long after) {
        return """
                {"type":"hello","protocol_version":1,"csrf_token":"token","cursor":{"epoch":"%s","after_seq":%d}}
                """.formatted(epoch, after);
    }
}
