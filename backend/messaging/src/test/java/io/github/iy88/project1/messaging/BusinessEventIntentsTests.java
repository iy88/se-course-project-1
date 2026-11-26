package io.github.iy88.project1.messaging;

import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationKind;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationRef;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class BusinessEventIntentsTests {
    private static final Set<Long> RECIPIENTS = Set.of(14L);
    private final WriteTransaction transaction = mock(WriteTransaction.class);

    @BeforeEach
    void authenticatedReader() {
        when(transaction.context()).thenReturn(new ExecutionContext(UUID.randomUUID(),
                ExecutionContext.ActorKind.ACCOUNT, "14", UUID.randomUUID(), null, 1L, "test"));
    }

    @Test
    void notificationIntentsUseTheNotificationTransportSource() {
        BusinessEventIntents.notificationCreated(transaction, 14, 77, "notify:created");
        BusinessEventIntents.notificationRead(transaction, 77, "notify:read");

        verify(transaction).addEventIntent(RECIPIENTS, "notification_created", 1,
                new ResourceRef("notification", 77), "notify:created", null, null);
        verify(transaction).addEventIntent(RECIPIENTS, "notification_read", 1,
                new ResourceRef("notification", 77), "notify:read", null, null);
    }

    @Test
    void conversationIntentsUseTheNamedSourceMessageReferenceAndReadSequence() {
        var conversation = new ConversationRef(ConversationKind.TRADE, 5);
        var message = new ResourceRef("trade_message", 8);

        BusinessEventIntents.messageCreated(transaction, RECIPIENTS, conversation, 8, "message:8");
        BusinessEventIntents.messageRead(transaction, conversation, 8, "read:8");
        BusinessEventIntents.conversationArchived(transaction, RECIPIENTS, conversation, "archive:5");

        verify(transaction).addEventIntent(RECIPIENTS, "message_created", 1, conversation.resource(),
                "message:8", message, null);
        verify(transaction).addEventIntent(RECIPIENTS, "message_read", 1, conversation.resource(),
                "read:8", null, 8L);
        verify(transaction).addEventIntent(RECIPIENTS, "conversation_archived", 1, conversation.resource(),
                "archive:5", null, null);
    }

    @Test
    void sourceChangedUsesTheRegisteredResourceReference() {
        var source = new ResourceRef("product", 31);

        BusinessEventIntents.sourceChanged(transaction, RECIPIENTS, source, "product:31");

        verify(transaction).addEventIntent(eq(RECIPIENTS), eq("source_changed"), eq(1), eq(source),
                eq("product:31"), isNull(), isNull());
    }
}
