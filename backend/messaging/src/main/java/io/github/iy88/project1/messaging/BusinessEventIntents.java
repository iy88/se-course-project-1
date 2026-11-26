package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.Set;

/**
 * Named transport event references for business writers. Business state remains owned by
 * notifications and conversations; this class only registers the C2 intent in the same write.
 */
public final class BusinessEventIntents {
    private static final int SCHEMA_VERSION = 1;

    private BusinessEventIntents() {}

    public static EventIntent.Batch notificationCreated(WriteTransaction transaction, long recipient,
                                                        long notificationId, String intentKey) {
        return transaction.addEventIntent(Set.of(recipient), "notification_created", SCHEMA_VERSION,
                new ResourceRef("notification", notificationId), intentKey, null, null);
    }

    public static EventIntent.Batch notificationRead(WriteTransaction transaction,
                                                     long notificationId, String intentKey) {
        return transaction.addEventIntent(Set.of(reader(transaction)), "notification_read", SCHEMA_VERSION,
                new ResourceRef("notification", notificationId), intentKey, null, null);
    }

    public static EventIntent.Batch messageCreated(WriteTransaction transaction, Set<Long> recipients,
                                                   RealtimeEventSources.ConversationRef conversation,
                                                   long messageId, String intentKey) {
        return transaction.addEventIntent(recipients, "message_created", SCHEMA_VERSION,
                conversation.resource(), intentKey, conversation.message(messageId), null);
    }

    public static EventIntent.Batch messageRead(WriteTransaction transaction,
                                                RealtimeEventSources.ConversationRef conversation,
                                                long lastReadSequence, String intentKey) {
        return transaction.addEventIntent(Set.of(reader(transaction)), "message_read", SCHEMA_VERSION,
                conversation.resource(), intentKey, null, lastReadSequence);
    }

    public static EventIntent.Batch conversationArchived(WriteTransaction transaction, Set<Long> recipients,
                                                         RealtimeEventSources.ConversationRef conversation,
                                                         String intentKey) {
        return transaction.addEventIntent(recipients, "conversation_archived", SCHEMA_VERSION,
                conversation.resource(), intentKey, null, null);
    }

    public static EventIntent.Batch sourceChanged(WriteTransaction transaction, Set<Long> recipients,
                                                  ResourceRef source, String intentKey) {
        return transaction.addEventIntent(recipients, "source_changed", SCHEMA_VERSION,
                source, intentKey, null, null);
    }

    private static long reader(WriteTransaction transaction) {
        var actor = transaction.context();
        if (actor.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new IllegalArgumentException("Read synchronization requires an account actor");
        }
        return Long.parseLong(actor.actorId());
    }
}
