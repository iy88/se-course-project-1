package io.github.iy88.project1.conversation.application;

import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Service;

/**
 * Trade-facing conversation capability. The trade module owns trade records; this facade only
 * creates, appends to and archives the one conversation attached to a trade.
 */
@Lazy
@Service
public class TradeConversations {
    private final ConversationStore store;

    public TradeConversations(ConversationStore store) {
        this.store = store;
    }

    public record Ensured(long conversationId, boolean created) {
    }

    public record Conversation(long conversationId, long tradeId, Instant archivedAt) {
    }

    public record Message(long messageId, long seq, Instant createdAt) {
    }

    public Ensured ensure(WriteTransaction transaction, long tradeId, long buyerId, long sellerId) {
        boolean existed = store.findTrade(tradeId).isPresent();
        var conversation = store.ensureTrade(transaction, tradeId, buyerId, sellerId);
        return new Ensured(conversation.id(), !existed);
    }

    public Optional<Conversation> find(long tradeId) {
        return store.findTrade(tradeId).map(TradeConversations::view);
    }

    public Conversation lockConversation(WriteTransaction transaction, long conversationId) {
        return view(store.lockTrade(transaction, conversationId));
    }

    public Conversation lockByTrade(WriteTransaction transaction, long tradeId) {
        return view(store.lockTradeByTradeId(transaction, tradeId));
    }

    public Message appendText(WriteTransaction transaction, long tradeId, long senderAccountId, String body) {
        var conversation = store.lockTradeByTradeId(transaction, tradeId);
        return message(store.appendTradeText(transaction, conversation, senderAccountId, body));
    }

    public Message appendSystemEvent(WriteTransaction transaction, long tradeId, UUID businessEventId,
                                     String eventType, String body, String sourceType, Long sourceId) {
        var conversation = store.lockTradeByTradeId(transaction, tradeId);
        return message(store.appendTradeSystemEvent(transaction, conversation, businessEventId, eventType, body,
                sourceType, sourceId));
    }

    public boolean archive(WriteTransaction transaction, long tradeId) {
        var conversation = store.lockTradeByTradeId(transaction, tradeId);
        return store.archiveTrade(transaction, conversation);
    }

    private static Conversation view(TradeConversation conversation) {
        return new Conversation(conversation.id(), conversation.tradeId(), conversation.archivedAt());
    }

    private static Message message(TradeMessage message) {
        return new Message(message.id(), message.seq(), message.createdAt());
    }
}
