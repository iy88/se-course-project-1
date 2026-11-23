package io.github.iy88.project1.conversation.persistence;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import org.springframework.context.annotation.Lazy;
import org.springframework.data.domain.PageRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/** Read-only conversation access; callers apply participant and visibility rules. */
@Lazy
@Service
@Profile("infrastructure")
public class ConversationReader {
    private final ChatConversationRepository chats;
    private final TradeConversationRepository trades;
    private final ChatMessageRepository chatMessages;
    private final TradeMessageRepository tradeMessages;
    private final CaseMessageRepository caseMessages;

    public ConversationReader(ChatConversationRepository chats, TradeConversationRepository trades,
                              ChatMessageRepository chatMessages, TradeMessageRepository tradeMessages,
                              CaseMessageRepository caseMessages) {
        this.chats = chats;
        this.trades = trades;
        this.chatMessages = chatMessages;
        this.tradeMessages = tradeMessages;
        this.caseMessages = caseMessages;
    }

    public List<ChatConversation> chatConversations(long accountId) {
        return chats.findByAccountLowIdOrAccountHighId(accountId, accountId);
    }

    public Optional<ChatMessage> chatMessage(long messageId) {
        return chatMessages.findById(messageId);
    }

    public Optional<TradeMessage> tradeMessage(long messageId) {
        return tradeMessages.findById(messageId);
    }

    public Optional<CaseMessage> caseMessage(long messageId) {
        return caseMessages.findById(messageId);
    }

    public List<TradeConversation> tradeConversations(Collection<Long> tradeIds) {
        if (tradeIds.isEmpty()) {
            return List.of();
        }
        return trades.findByTradeIdIn(tradeIds);
    }

    public Optional<ChatMessage> chatLastMessage(long conversationId) {
        return chatMessages.findTopByChatConversationIdOrderBySeqDesc(conversationId);
    }

    public Optional<TradeMessage> tradeLastMessage(long conversationId) {
        return tradeMessages.findTopByTradeConversationIdOrderBySeqDesc(conversationId);
    }

    public List<ChatMessage> chatMessages(long conversationId, Long beforeSeq, Long afterSeq, int limit) {
        var page = PageRequest.of(0, limit);
        if (afterSeq != null) {
            return chatMessages.findByChatConversationIdAndSeqGreaterThanOrderBySeqAsc(conversationId, afterSeq, page);
        }
        if (beforeSeq != null) {
            return reversed(chatMessages.findByChatConversationIdAndSeqLessThanOrderBySeqDesc(conversationId,
                    beforeSeq, page));
        }
        return reversed(chatMessages.findByChatConversationIdOrderBySeqDesc(conversationId, page));
    }

    public List<TradeMessage> tradeMessages(long conversationId, Long beforeSeq, Long afterSeq, int limit) {
        var page = PageRequest.of(0, limit);
        if (afterSeq != null) {
            return tradeMessages.findByTradeConversationIdAndSeqGreaterThanOrderBySeqAsc(conversationId, afterSeq,
                    page);
        }
        if (beforeSeq != null) {
            return reversed(tradeMessages.findByTradeConversationIdAndSeqLessThanOrderBySeqDesc(conversationId,
                    beforeSeq, page));
        }
        return reversed(tradeMessages.findByTradeConversationIdOrderBySeqDesc(conversationId, page));
    }

    public List<CaseMessage> caseMessages(long conversationId, Long beforeSeq, Long afterSeq, int limit) {
        var page = PageRequest.of(0, limit);
        if (afterSeq != null) {
            return caseMessages.findByCaseConversationIdAndSeqGreaterThanOrderBySeqAsc(conversationId, afterSeq, page);
        }
        if (beforeSeq != null) {
            return reversed(caseMessages.findByCaseConversationIdAndSeqLessThanOrderBySeqDesc(conversationId,
                    beforeSeq, page));
        }
        return reversed(caseMessages.findByCaseConversationIdOrderBySeqDesc(conversationId, page));
    }

    private static <T> List<T> reversed(List<T> descending) {
        var ordered = new ArrayList<>(descending);
        Collections.reverse(ordered);
        return ordered;
    }
}
