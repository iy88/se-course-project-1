package io.github.iy88.project1.conversation.persistence;

import java.util.Optional;
import org.springframework.data.repository.Repository;

interface ChatReadProgressRepository extends Repository<ChatReadProgress, ChatReadProgress.Key> {
    ChatReadProgress save(ChatReadProgress progress);

    Optional<ChatReadProgress> findById(ChatReadProgress.Key key);

    Optional<ChatReadProgress> findByChatConversationIdAndAccountId(long chatConversationId, long accountId);
}

interface TradeReadProgressRepository extends Repository<TradeReadProgress, TradeReadProgress.Key> {
    TradeReadProgress save(TradeReadProgress progress);

    Optional<TradeReadProgress> findById(TradeReadProgress.Key key);

    Optional<TradeReadProgress> findByTradeConversationIdAndAccountId(long tradeConversationId, long accountId);
}

interface CaseReadProgressRepository extends Repository<CaseReadProgress, CaseReadProgress.Key> {
    CaseReadProgress save(CaseReadProgress progress);

    Optional<CaseReadProgress> findById(CaseReadProgress.Key key);

    Optional<CaseReadProgress> findByCaseConversationIdAndAccountId(long caseConversationId, long accountId);
}
