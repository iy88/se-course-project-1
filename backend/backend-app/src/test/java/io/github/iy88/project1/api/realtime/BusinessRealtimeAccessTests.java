package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.messaging.RealtimeEventSources;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationKind;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationRef;
import io.github.iy88.project1.messaging.RealtimeEventSources.MessageHint;
import io.github.iy88.project1.messaging.RealtimeEventSources.NotificationHint;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.UserEvents;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class BusinessRealtimeAccessTests {
    private static final Instant OCCURRED_AT = Instant.parse("2026-11-20T00:00:00Z");
    private static final Instant READ_AT = Instant.parse("2026-11-20T01:02:03Z");
    private final RealtimeSessions sessions = mock(RealtimeSessions.class);
    private final RealtimeEventSources.Notifications notifications =
            mock(RealtimeEventSources.Notifications.class);
    private final RealtimeEventSources.Conversations conversations =
            mock(RealtimeEventSources.Conversations.class);
    private final ExecutionContext context = new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, "14", UUID.randomUUID(), null, 1L, "test");
    private final RealtimeAccess.Session session = new RealtimeAccess.Session(14, UUID.randomUUID(), 1L, "test");

    @Test
    void notificationReadabilityIsIndependentFromTheLinkedBusinessSource() {
        var linkedSource = new ResourceRef("product", 900);
        var payload = new ResourceRef("notification", 77);
        when(notifications.read(context, 77)).thenReturn(Optional.of(new NotificationHint(null)));
        var access = access(List.of(source(linkedSource.type(), false)));

        var data = entries(access.project(context, event("notification_created", 1, linkedSource, payload, null)));

        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of("notification_id", "77"));
        verify(notifications).read(context, 77);
        verifyNoInteractions(conversations);
    }

    @Test
    void notificationCreatedUsesTheCanonicalNotificationSourceWithoutExtraFields() {
        var source = new ResourceRef("notification", 77);
        when(notifications.read(context, 77)).thenReturn(Optional.of(new NotificationHint(null)));
        var access = access(List.of());

        var data = entries(access.project(context, event("notification_created", 1, source, null, null)));

        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of("notification_id", "77"));
    }

    @Test
    void notificationReadCarriesTheAuthoritativeFirstReadAt() {
        var source = new ResourceRef("notification", 77);
        when(notifications.read(context, 77)).thenReturn(Optional.of(new NotificationHint(READ_AT)));
        var access = access(List.of());

        var data = entries(access.project(context, event("notification_read", 1, source, null, null)));

        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of(
                "notification_id", "77", "read_at", READ_AT));
    }

    @Test
    void unreadableNotificationsAndMissingAuthoritativeReadTimesAreSuppressed() {
        var source = new ResourceRef("notification", 77);
        when(notifications.read(context, 77)).thenReturn(Optional.empty());
        var access = access(List.of());

        assertThat(access.project(context, event("notification_created", 1, source, null, null))).isEmpty();

        when(notifications.read(context, 77)).thenReturn(Optional.of(new NotificationHint(null)));
        assertThat(access.project(context, event("notification_read", 1, source, null, null))).isEmpty();
    }

    @Test
    void messageCreatedProjectsOnlyWhitelistedConversationAndMessageFields() {
        var conversation = new ConversationRef(ConversationKind.CHAT, 5);
        var message = new ResourceRef("chat_message", 8);
        when(conversations.readMessage(context, conversation, 8)).thenReturn(Optional.of(new MessageHint(12, null)));
        var access = access(List.of());

        var data = entries(access.project(context,
                event("message_created", 1, conversation.resource(), message, null)));

        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of(
                "conversation_kind", "chat", "conversation_id", "5", "message_id", "8", "message_seq", 12L));

        when(conversations.readMessage(context, conversation, 8)).thenReturn(Optional.empty());
        assertThat(access.project(context, event("message_created", 1, conversation.resource(), message, null)))
                .isEmpty();
    }

    @Test
    void aMessageReferenceMustMatchTheConversationKind() {
        var conversation = new ConversationRef(ConversationKind.CHAT, 5);
        var unrelated = new ResourceRef("case_message", 8);

        assertThat(access(List.of()).project(context,
                event("message_created", 1, conversation.resource(), unrelated, null))).isEmpty();
        verifyNoInteractions(conversations);
    }

    @Test
    void messageCreatedAddsBusinessEventIdOnlyWhenTheSystemMessageProvidesOne() {
        var conversation = new ConversationRef(ConversationKind.TRADE, 6);
        var message = new ResourceRef("trade_message", 9);
        var businessEvent = UUID.randomUUID();
        when(conversations.readMessage(context, conversation, 9))
                .thenReturn(Optional.of(new MessageHint(3, businessEvent)));
        var access = access(List.of());

        var data = entries(access.project(context,
                event("message_created", 1, conversation.resource(), message, null)));

        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of(
                "conversation_kind", "trade", "conversation_id", "6", "message_id", "9",
                "message_seq", 3L, "business_event_id", businessEvent));
    }

    @Test
    void messageReadUsesTheAuthoritativeSourceSequenceAndCurrentReadAccess() {
        var conversation = new ConversationRef(ConversationKind.CASE, 7);
        when(conversations.canRead(context, conversation)).thenReturn(true);
        var access = access(List.of());

        var data = entries(access.project(context,
                event("message_read", 1, conversation.resource(), null, 42L)));
        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of(
                "conversation_kind", "case", "conversation_id", "7", "last_read_seq", 42L));

        when(conversations.canRead(context, conversation)).thenReturn(false);
        assertThat(access.project(context, event("message_read", 1, conversation.resource(), null, 43L))).isEmpty();
        assertThat(access.project(context, event("message_read", 1, conversation.resource(), null, null))).isEmpty();
    }

    @Test
    void conversationArchivedContainsOnlyTheConversationReference() {
        var conversation = new ConversationRef(ConversationKind.CHAT, 5);
        when(conversations.canRead(context, conversation)).thenReturn(true);
        var access = access(List.of());

        var data = entries(access.project(context,
                event("conversation_archived", 1, conversation.resource(), null, null)));
        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of(
                "conversation_kind", "chat", "conversation_id", "5"));

        when(conversations.canRead(context, conversation)).thenReturn(false);
        assertThat(access.project(context,
                event("conversation_archived", 1, conversation.resource(), null, null))).isEmpty();
    }

    @Test
    void sourceChangedRequiresARegisteredCurrentSource() {
        var product = new ResourceRef("product", 31);
        var access = access(List.of(source(product.type(), true)));

        var data = entries(access.project(context, event("source_changed", 1, product, null, null)));
        assertThat(data).containsExactlyInAnyOrderEntriesOf(Map.of("source_type", "product", "source_id", "31"));
        assertThat(access.project(context, event("source_changed", 1, new ResourceRef("order", 32), null, null)))
                .isEmpty();

        var denied = access(List.of(source("product", false)));
        assertThat(denied.project(context, event("source_changed", 1, product, null, null))).isEmpty();
    }

    @Test
    void unknownTypesAndVersionsAreSuppressedWithoutAffectingBusinessProjection() {
        var notification = new ResourceRef("notification", 77);
        var conversation = new ConversationRef(ConversationKind.CHAT, 5);
        when(notifications.read(context, 77)).thenReturn(Optional.of(new NotificationHint(null)));
        when(conversations.canRead(context, conversation)).thenReturn(true);
        var access = access(List.of());

        assertThat(access.project(context, event("notification_created", 2, notification, null, null))).isEmpty();
        assertThat(access.project(context, event("message_read", 2, conversation.resource(), null, 2L))).isEmpty();
        assertThat(access.project(context, event("unknown_changed", 1, notification, null, null))).isEmpty();

        assertThat(entries(access.project(context,
                event("notification_created", 1, notification, null, null))))
                .containsExactlyInAnyOrderEntriesOf(Map.of("notification_id", "77"));
        assertThat(entries(access.project(context,
                event("message_read", 1, conversation.resource(), null, 2L))))
                .containsExactlyInAnyOrderEntriesOf(Map.of(
                        "conversation_kind", "chat", "conversation_id", "5", "last_read_seq", 2L));
    }

    @Test
    void requiresTheSessionAndBothBusinessReadAdapters() {
        assertThatThrownBy(() -> new BusinessRealtimeAccess(null, notifications, conversations, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("RealtimeSessions");
        assertThatThrownBy(() -> new BusinessRealtimeAccess(sessions, null, conversations, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("Notifications");
        assertThatThrownBy(() -> new BusinessRealtimeAccess(sessions, notifications, null, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("Conversations");
    }

    @Test
    void authenticationUsesTheCookiePortAndRejectsMissingSessionsWith401() {
        var request = mock(HttpServletRequest.class);
        when(sessions.resolve(request)).thenReturn(Optional.empty());
        var access = access(List.of());

        assertThatThrownBy(() -> access.authenticate(request))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.status()).isEqualTo(401);
                    assertThat(error.code()).isEqualTo("AUTHENTICATION_REQUIRED");
                });

        when(sessions.resolve(request)).thenReturn(Optional.of(session));
        assertThat(access.authenticate(request)).isEqualTo(session);
        access.requireCurrent(session);
        access.requireHello(session, "token");
        verify(sessions).requireCurrent(session);
        verify(sessions).requireCsrf(session, "token");
    }

    private BusinessRealtimeAccess access(List<RealtimeEventSources.SourceAccess> sources) {
        return new BusinessRealtimeAccess(sessions, notifications, conversations, sources);
    }

    private static Map<String, Object> entries(Optional<Map<String, ?>> data) {
        return new LinkedHashMap<>(data.orElseThrow());
    }

    private static RealtimeEventSources.SourceAccess source(String type, boolean readable) {
        return new RealtimeEventSources.SourceAccess() {
            @Override
            public String sourceType() {
                return type;
            }

            @Override
            public boolean canRead(ExecutionContext context, ResourceRef source) {
                return readable;
            }
        };
    }

    private static UserEvents.Event event(String type, int version, ResourceRef source, ResourceRef payload,
                                          Long sourceSequence) {
        return new UserEvents.Event(UUID.randomUUID(), 1L, type, version, source, payload, sourceSequence,
                null, OCCURRED_AT);
    }

    private static UserEvents.Event event(String type, int version, ResourceRef source, ResourceRef payload) {
        return event(type, version, source, payload, null);
    }
}
