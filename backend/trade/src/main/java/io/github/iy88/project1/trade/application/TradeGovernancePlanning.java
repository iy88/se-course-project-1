package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.util.Map;
import java.util.TreeSet;

/**
 * Assembles the trade governance lock plans. The named governance commands and the case
 * enforcement subject plan keep their original read order, optional product/conversation keys and
 * account modes; the public entry points and lock callbacks stay on {@link TradeApplication}.
 */
final class TradeGovernancePlanning {
    private final TradeRepository repository;
    private final TradePorts.Conversation conversations;
    private final TradeQueries queries;

    TradeGovernancePlanning(TradeRepository repository, TradePorts.Conversation conversations,
                            TradeQueries queries) {
        this.repository = repository;
        this.conversations = conversations;
        this.queries = queries;
    }

    /** Named governance command plan with an optional product lock and optional conversation lock. */
    LockPlan governance(long manager, long tradeId, long caseId, boolean product) {
        return governance(manager, tradeId, caseId, product, false);
    }

    /** Freeze/lift plan: both trade parties take the exclusive account lock. */
    LockPlan freezeChange(long manager, long tradeId, long caseId) {
        return governance(manager, tradeId, caseId, false, true);
    }

    /** Case enforcement plan whose exact conversation row is required by the lock callbacks. */
    TradePorts.CaseEnforcementPlan enforcement(long managerId, long tradeId, long caseId, boolean product) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        long conversationId = queries.requireConversationId(tradeId);
        var resources = new TreeSet<LockPlan.Key>();
        if (product) {
            resources.add(TradeWriteSupport.productKey(trade.productId()));
        }
        resources.add(TradeWriteSupport.tradeKey(tradeId));
        resources.add(TradeWriteSupport.caseKey(caseId));
        resources.add(TradeWriteSupport.conversationKey(conversationId));
        // Freeze/lift/adjust changes a party's qualification, so both trade parties take the
        // exclusive account lock while the manager remains shared.
        return new TradePorts.CaseEnforcementPlan(
                new LockPlan(partyAccounts(managerId, trade, true), resources),
                conversationId, product ? trade.productId() : null);
    }

    private LockPlan governance(long manager, long tradeId, long caseId, boolean product,
                                boolean exclusiveParties) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var resources = new TreeSet<LockPlan.Key>();
        if (product) {
            resources.add(TradeWriteSupport.productKey(trade.productId()));
        }
        resources.add(TradeWriteSupport.tradeKey(tradeId));
        resources.add(TradeWriteSupport.caseKey(caseId));
        conversations.find(tradeId).ifPresent(id -> resources.add(TradeWriteSupport.conversationKey(id)));
        return new LockPlan(partyAccounts(manager, trade, exclusiveParties), resources);
    }

    /**
     * Manager plus both trade parties. A qualification-changing action takes the exclusive lock
     * for the parties, so product writes and new purchases that read the party freeze under their
     * shared account lock either finish before the freeze or observe it after it commits.
     */
    private static Map<Long, LockPlan.AccountMode> partyAccounts(long managerId, Trade trade,
                                                                 boolean exclusiveParties) {
        var accounts = TradeWriteSupport.partyAccounts(trade, exclusiveParties);
        // A manager who is also a party keeps the stronger party mode.
        accounts.putIfAbsent(managerId, LockPlan.AccountMode.SHARED);
        return accounts;
    }
}
