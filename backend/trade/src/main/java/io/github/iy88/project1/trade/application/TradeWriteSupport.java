package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.WaitEndReason;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;
import tools.jackson.databind.json.JsonMapper;

/** Package-private helpers shared by the trade write use cases. */
final class TradeWriteSupport {
    private TradeWriteSupport() {
    }

    static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new IllegalStateException("Account execution context required");
        }
        return Long.parseLong(context.actorId());
    }

    static long other(Trade trade, long accountId) {
        return trade.buyerId() == accountId ? trade.sellerId() : trade.buyerId();
    }

    static Instant now(Clock clock, TradeRepository repository) {
        return clock == null ? repository.databaseNow() : clock.instant().truncatedTo(ChronoUnit.MICROS);
    }

    static void requireWrite(TradePorts.Accounts accounts, long accountId) {
        var qualification = accounts.qualification(accountId);
        if (!qualification.exists()) {
            throw Trade.actionNotAllowed();
        }
        if (qualification.writeRestricted()) {
            throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前受限");
        }
    }

    static void requireNotFrozen(TradeRepository repository, long tradeId) {
        if (!repository.activeFreezes(tradeId).isEmpty()) {
            throw new BusinessError("TRADE_FROZEN", 409, "交易已冻结");
        }
    }

    static Map<Long, LockPlan.AccountMode> sharedAccounts(Collection<Long> accountIds) {
        var map = new TreeMap<Long, LockPlan.AccountMode>();
        for (long id : accountIds) {
            map.put(id, LockPlan.AccountMode.SHARED);
        }
        return map;
    }

    static LockPlan.Key productKey(long productId) {
        return new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(productId));
    }

    static LockPlan.Key tradeKey(long tradeId) {
        return new LockPlan.Key(LockPlan.Domain.TRADE, List.of(tradeId));
    }

    static LockPlan.Key caseKey(long caseId) {
        return new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId));
    }

    /**
     * Participant trade plan: caller plus both parties, optional product and case keys, and the
     * trade conversation when one already exists.
     */
    static LockPlan prepareTrade(TradeRepository repository, TradePorts.Conversation conversations,
                                 long actor, long tradeId, boolean product, Long caseId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var accountIds = new TreeSet<Long>(List.of(actor, trade.buyerId(), trade.sellerId()));
        var resources = new TreeSet<LockPlan.Key>();
        if (product) {
            resources.add(productKey(trade.productId()));
        }
        resources.add(tradeKey(tradeId));
        conversations.find(tradeId).ifPresent(id -> resources.add(conversationKey(id)));
        if (caseId != null) {
            resources.add(caseKey(caseId));
        }
        return new LockPlan(sharedAccounts(accountIds), resources);
    }

    static void audit(JsonMapper json, WriteTransaction transaction, String action, long tradeId, ResourceRef basis) {
        var facts = json.createObjectNode();
        facts.put("action", "audit");
        facts.put("trade_id", tradeId);
        transaction.audit(action, new ResourceRef("trade", tradeId), basis, facts);
    }

    static void replayTrade(TradeRepository repository, ExecutionContext context, ResourceRef resource) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT || resource == null
                || !"trade".equals(resource.type())) {
            return;
        }
        long actor = actor(context);
        var trade = repository.find(resource.id()).orElseThrow(Trade::notVisible);
        trade.requireParticipant(actor);
    }

    static BusinessError inputInvalid(String message) {
        return new BusinessError("INPUT_INVALID", 422, message);
    }

    static String requiredText(String value, int max, String field) {
        if (value == null || value.isBlank() || value.length() > max) {
            throw inputInvalid(field + "不能为空且长度不能超过" + max);
        }
        return value.trim();
    }

    static Map<Long, LockPlan.AccountMode> partyAccounts(Trade trade, boolean exclusiveParties) {
        var accounts = new TreeMap<Long, LockPlan.AccountMode>();
        var partyMode = exclusiveParties ? LockPlan.AccountMode.EXCLUSIVE : LockPlan.AccountMode.SHARED;
        accounts.put(trade.buyerId(), partyMode);
        accounts.put(trade.sellerId(), partyMode);
        return accounts;
    }

    static Trade changed(Trade trade, TradeStatus status, Long activeAgreementId, String closeReason,
                         String terminalReason, Instant respondedAt, Instant endedAt, Instant now) {
        if (status != trade.status()) {
            trade.status().requireTransition(status);
        }
        return new Trade(trade.id(), trade.productId(), trade.buyerId(), trade.sellerId(), status,
                trade.requestNote(), activeAgreementId, trade.version() + 1, closeReason, terminalReason,
                trade.requestedAt(), respondedAt, endedAt, trade.createdAt(), now);
    }

    static void requirePartyFreezeLocks(WriteTransaction transaction, Trade trade) {
        transaction.requireExclusiveAccount(trade.buyerId());
        transaction.requireExclusiveAccount(trade.sellerId());
    }

    static LockPlan.Key conversationKey(long conversationId) {
        return new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(conversationId));
    }

    static long requireConversation(WriteTransaction transaction, TradePorts.Conversation conversations,
                                    TradeQueries queries, long tradeId) {
        long conversationId = queries.requireConversationId(tradeId);
        conversations.lockConversation(transaction, conversationId);
        return conversationId;
    }

    static void endWait(TradeRepository repository, long tradeId, WaitEndReason reason, Instant now) {
        var wait = repository.waitFor(tradeId).orElse(null);
        if (wait != null && !wait.ended()) {
            repository.saveWait(tradeId, wait.end(now, reason));
        }
    }

    static void scheduleTimeout(TaskSchedules schedules, long tradeId, TradeModels.Wait wait, Instant now) {
        var deadline = wait.deadline(now);
        String trigger = tradeId + ":" + wait.startedAt().toEpochMilli() + ":"
                + (wait.activeSince() == null ? "paused" : wait.activeSince().toEpochMilli()) + ":"
                + deadline.toEpochMilli();
        schedules.schedule(new TaskSchedules.Spec(TradeTimeoutHandler.KIND, new ResourceRef("trade", tradeId),
                trigger, wait.fingerprint(), deadline, wait.policyVersion()));
    }
}
