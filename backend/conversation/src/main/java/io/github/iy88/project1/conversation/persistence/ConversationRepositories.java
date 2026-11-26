package io.github.iy88.project1.conversation.persistence;

import jakarta.persistence.LockModeType;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

interface ChatConversationRepository extends Repository<ChatConversation, Long> {
    ChatConversation save(ChatConversation conversation);

    Optional<ChatConversation> findById(long id);

    Optional<ChatConversation> findByAccountLowIdAndAccountHighId(long accountLowId, long accountHighId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from ChatConversation c where c.id = :id")
    Optional<ChatConversation> lockById(long id);

    @Query("""
            select c from ChatConversation c
            where c.accountLowId = :accountId or c.accountHighId = :accountId
            order by c.createdAt desc, c.id desc
            """)
    List<ChatConversation> listForAccount(long accountId, Pageable page);

    List<ChatConversation> findByAccountLowIdOrAccountHighId(long accountLowId, long accountHighId);

    long countByAccountLowIdOrAccountHighId(long accountLowId, long accountHighId);
}

interface TradeConversationRepository extends Repository<TradeConversation, Long> {
    TradeConversation save(TradeConversation conversation);

    Optional<TradeConversation> findById(long id);

    Optional<TradeConversation> findByTradeId(long tradeId);

    List<TradeConversation> findByTradeIdIn(Collection<Long> tradeIds);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from TradeConversation c where c.id = :id")
    Optional<TradeConversation> lockById(long id);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from TradeConversation c where c.tradeId = :tradeId")
    Optional<TradeConversation> lockByTradeId(long tradeId);
}

interface CaseConversationRepository extends Repository<CaseConversation, Long> {
    CaseConversation save(CaseConversation conversation);

    Optional<CaseConversation> findById(long id);

    Optional<CaseConversation> findByCaseIdAndRelatedAccountId(long caseId, long relatedAccountId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from CaseConversation c where c.id = :id")
    Optional<CaseConversation> lockById(long id);
}
