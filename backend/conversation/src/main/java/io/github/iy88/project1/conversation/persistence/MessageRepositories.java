package io.github.iy88.project1.conversation.persistence;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.domain.Pageable;
import org.springframework.data.repository.Repository;

interface ChatMessageRepository extends Repository<ChatMessage, Long> {
    ChatMessage save(ChatMessage message);

    Optional<ChatMessage> findById(long id);

    Optional<ChatMessage> findTopByChatConversationIdOrderBySeqDesc(long conversationId);

    List<ChatMessage> findByChatConversationIdOrderBySeqDesc(long conversationId, Pageable page);

    List<ChatMessage> findByChatConversationIdAndSeqLessThanOrderBySeqDesc(long conversationId, long seq, Pageable page);

    List<ChatMessage> findByChatConversationIdAndSeqGreaterThanOrderBySeqAsc(long conversationId, long seq,
                                                                            Pageable page);

    long countByChatConversationIdAndSeqGreaterThan(long conversationId, long seq);
}

interface TradeMessageRepository extends Repository<TradeMessage, Long> {
    TradeMessage save(TradeMessage message);

    Optional<TradeMessage> findById(long id);

    Optional<TradeMessage> findTopByTradeConversationIdOrderBySeqDesc(long conversationId);

    Optional<TradeMessage> findByBusinessEventId(UUID businessEventId);

    List<TradeMessage> findByTradeConversationIdOrderBySeqDesc(long conversationId, Pageable page);

    List<TradeMessage> findByTradeConversationIdAndSeqLessThanOrderBySeqDesc(long conversationId, long seq,
                                                                             Pageable page);

    List<TradeMessage> findByTradeConversationIdAndSeqGreaterThanOrderBySeqAsc(long conversationId, long seq,
                                                                              Pageable page);

    long countByTradeConversationIdAndSeqGreaterThan(long conversationId, long seq);
}

interface CaseMessageRepository extends Repository<CaseMessage, Long> {
    CaseMessage save(CaseMessage message);

    Optional<CaseMessage> findById(long id);

    Optional<CaseMessage> findTopByCaseConversationIdOrderBySeqDesc(long conversationId);

    Optional<CaseMessage> findByBusinessEventId(UUID businessEventId);

    List<CaseMessage> findByCaseConversationIdOrderBySeqDesc(long conversationId, Pageable page);

    List<CaseMessage> findByCaseConversationIdAndSeqLessThanOrderBySeqDesc(long conversationId, long seq,
                                                                           Pageable page);

    List<CaseMessage> findByCaseConversationIdAndSeqGreaterThanOrderBySeqAsc(long conversationId, long seq,
                                                                            Pageable page);

    long countByCaseConversationIdAndSeqGreaterThan(long conversationId, long seq);
}
