package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
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

    static Map<Long, LockPlan.AccountMode> sharedAccounts(Collection<Long> accountIds) {
        var map = new TreeMap<Long, LockPlan.AccountMode>();
        for (long id : accountIds) {
            map.put(id, LockPlan.AccountMode.SHARED);
        }
        return map;
    }

    static LockPlan.Key tradeKey(long tradeId) {
        return new LockPlan.Key(LockPlan.Domain.TRADE, List.of(tradeId));
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
}
