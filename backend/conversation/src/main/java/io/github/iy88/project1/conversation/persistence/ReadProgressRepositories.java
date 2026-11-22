package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

interface ChatReadProgressRepository extends Repository<ChatReadProgress, ChatReadProgress.Key> {
    ChatReadProgress save(ChatReadProgress progress);

    Optional<ChatReadProgress> findById(ChatReadProgress.Key key);

    Optional<ChatReadProgress> findByChatConversationIdAndAccountId(long chatConversationId, long accountId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select p from ChatReadProgress p
            where p.chatConversationId = :conversationId and p.accountId = :accountId
            """)
    Optional<ChatReadProgress> lockByConversationAndAccount(long conversationId, long accountId);
}

interface TradeReadProgressRepository extends Repository<TradeReadProgress, TradeReadProgress.Key> {
    TradeReadProgress save(TradeReadProgress progress);

    Optional<TradeReadProgress> findById(TradeReadProgress.Key key);

    Optional<TradeReadProgress> findByTradeConversationIdAndAccountId(long tradeConversationId, long accountId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select p from TradeReadProgress p
            where p.tradeConversationId = :conversationId and p.accountId = :accountId
            """)
    Optional<TradeReadProgress> lockByConversationAndAccount(long conversationId, long accountId);
}

interface CaseReadProgressRepository extends Repository<CaseReadProgress, CaseReadProgress.Key> {
    CaseReadProgress save(CaseReadProgress progress);

    Optional<CaseReadProgress> findById(CaseReadProgress.Key key);

    Optional<CaseReadProgress> findByCaseConversationIdAndAccountId(long caseConversationId, long accountId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select p from CaseReadProgress p
            where p.caseConversationId = :conversationId and p.accountId = :accountId
            """)
    Optional<CaseReadProgress> lockByConversationAndAccount(long conversationId, long accountId);
}
