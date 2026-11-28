package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.FreezeSource;
import io.github.iy88.project1.trade.domain.TradeVocabulary.WaitEndReason;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import tools.jackson.databind.json.JsonMapper;

/**
 * Single-side confirmation timeout task: plan, locked applicability check and the abnormal/freeze
 * transition. The task adapter calls these steps through the public {@link TradeApplication}
 * entry points.
 */
final class TradeConfirmationTimeout {
    private final TradeRepository repository;
    private final TradeHistoryWriter historyWriter;
    private final TradeQueries queries;
    private final TaskSchedules schedules;
    private final Clock clock;
    private final TradePorts.Conversation conversations;
    private final TradePorts.Cases cases;
    private final TradePorts.Notifications notifications;
    private final JsonMapper json;

    TradeConfirmationTimeout(TradeRepository repository, TradeHistoryWriter historyWriter, TradeQueries queries,
                             TaskSchedules schedules, Clock clock, TradePorts.Conversation conversations,
                             TradePorts.Cases cases, TradePorts.Notifications notifications, JsonMapper json) {
        this.repository = repository;
        this.historyWriter = historyWriter;
        this.queries = queries;
        this.schedules = schedules;
        this.clock = clock;
        this.conversations = conversations;
        this.cases = cases;
        this.notifications = notifications;
        this.json = json;
    }

    LockPlan timeoutPlan(long tradeId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var resources = new TreeSet<LockPlan.Key>();
        resources.add(TradeWriteSupport.tradeKey(trade.id()));
        conversations.find(tradeId).ifPresent(id -> resources.add(TradeWriteSupport.conversationKey(id)));
        // The timeout freeze is a real freeze source for both parties, so it takes the same
        // exclusive party locks as an admin-case freeze before inserting the freeze row.
        return new LockPlan(TradeWriteSupport.partyAccounts(trade, true), resources);
    }

    void lockForTimeout(WriteTransaction transaction, long tradeId) {
        repository.lockTrade(transaction, tradeId);
        TradeWriteSupport.requireConversation(transaction, conversations, queries, tradeId);
    }

    boolean timeoutApplicable(long tradeId, String sourceVersion) {
        var trade = repository.find(tradeId).orElse(null);
        if (trade == null || trade.status() != TradeStatus.IN_PROGRESS) {
            return false;
        }
        var wait = repository.waitFor(tradeId).orElse(null);
        if (wait == null || wait.ended() || !wait.active()) {
            return false;
        }
        if (!wait.fingerprint().equals(sourceVersion)) {
            return false;
        }
        if (!repository.activeFreezes(tradeId).isEmpty()) {
            return false;
        }
        return repository.currentConfirmations(tradeId).size() == 1;
    }

    void applyTimeout(WriteTransaction transaction, ExecutionContext context, long tradeId, String sourceVersion) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        if (!timeoutApplicable(tradeId, sourceVersion)) {
            return;
        }
        TradeWriteSupport.requirePartyFreezeLocks(transaction, trade);
        var now = TradeWriteSupport.now(clock, repository);
        var wait = repository.waitFor(tradeId).orElseThrow();
        if (wait.elapsedSeconds(now) < wait.waitSeconds()) {
            // The database clock has not reached the stored deadline yet; move the trigger forward.
            TradeWriteSupport.scheduleTimeout(schedules, tradeId, wait, now);
            return;
        }
        long caseId = cases.openTimeoutCase(transaction, context, tradeId, "单方确认超时");
        repository.insertFreeze(tradeId, FreezeSource.TIMEOUT, caseId, "单方确认超时", now);
        TradeWriteSupport.endWait(repository, tradeId, WaitEndReason.TIMEOUT, now);
        var abnormal = TradeWriteSupport.changed(trade, TradeStatus.ABNORMAL, trade.activeAgreementId(),
                trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
        repository.save(abnormal);
        long conversationId = queries.requireConversationId(tradeId);
        UUID abnormalEvent = UUID.randomUUID();
        long abnormalHistory = historyWriter.history(transaction,
                trade, abnormal, "trade.abnormal", ActorKind.SYSTEM, null, "单方确认超时",
                "case:" + caseId, caseId, abnormalEvent, now);
        conversations.append(transaction, conversationId, abnormalEvent, "trade_abnormal",
                "单方确认超时，交易转异常", new ResourceRef("trade_transition", abnormalHistory));
        UUID frozenEvent = UUID.randomUUID();
        long frozenHistory = historyWriter.history(transaction,
                trade, abnormal, "trade.freeze", ActorKind.SYSTEM, null, "单方确认超时",
                "case:" + caseId, caseId, frozenEvent, now);
        conversations.append(transaction, conversationId, frozenEvent, "trade_frozen",
                "交易已冻结，等待管理员处理", new ResourceRef("trade_transition", frozenHistory));
        notifications.register(transaction, abnormalEvent, "trade.timeout", trade.id(),
                Set.of(trade.buyerId(), trade.sellerId()));
        TradeWriteSupport.audit(json, transaction, "trade.timeout", tradeId, new ResourceRef("case", caseId));
    }
}
