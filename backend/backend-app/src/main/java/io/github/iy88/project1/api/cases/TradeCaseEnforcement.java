package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.application.TradePorts;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

/**
 * Trade-backed case execution. It takes the trade subject rows once in the public product → trade
 * → case → trade-conversation order through the shared write transaction, then writes the locked
 * trade facts and the trade-owned downstream effects. Account, product, content and evaluation
 * actions remain with their own modules.
 */
final class TradeCaseEnforcement implements CasePorts.Enforcement {
    private static final Set<String> SUPPORTED = Set.of("freeze_trade", "adjust_trade_status");

    private final TradePorts.CaseEnforcement trades;
    private final TradePorts.Participation participation;

    TradeCaseEnforcement(TradePorts.CaseEnforcement trades, TradePorts.Participation participation) {
        this.trades = trades;
        this.participation = participation;
    }

    @Override
    public LockPlan plan(ExecutionContext context, long caseId, List<CaseRecords.EnforcementInstruction> items) {
        long manager = actor(context);
        var plan = new LockPlan(java.util.Map.of(), Set.of());
        for (var item : items) {
            requireSupported(item);
            plan = plan.merge(trades.prepare(manager, item.targetId(), caseId, adjust(item)).lockPlan());
        }
        return plan;
    }

    @Override
    public SubjectPlan lockCallbacks(ExecutionContext context, long caseId,
                                     List<CaseRecords.EnforcementInstruction> items) {
        long manager = actor(context);
        var subjects = SubjectPlan.empty();
        for (var item : items) {
            requireSupported(item);
            var prepared = trades.prepare(manager, item.targetId(), caseId, adjust(item));
            subjects = subjects.merge(callbacks(prepared, item.targetId()));
        }
        return subjects;
    }

    @Override
    public List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction, ExecutionContext context,
                                                        long caseId, String reason, String basisRef,
                                                        List<CaseRecords.EnforcementInstruction> items,
                                                        Instant occurredAt) {
        var outcomes = new ArrayList<CaseRecords.EnforcementOutcome>();
        for (var item : items) {
            requireSupported(item);
            var outcome = switch (item.action()) {
                case "freeze_trade" -> trades.freezeLocked(transaction, caseId, item.targetId(), basisRef, reason);
                case "adjust_trade_status" -> trades.adjustStatusLocked(transaction, caseId, item.targetId(),
                        item.expectedResult(), basisRef, reason);
                default -> throw unavailable();
            };
            trades.publishLocked(transaction, caseId, item.targetId(), item.action(), outcome, reason);
            outcomes.add(new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(), "trade",
                    item.targetId(), "trade_transition", outcome.transitionId(), "applied",
                    state(outcome.previousStatus(), outcome.previousPhase(), outcome.frozenBefore()),
                    state(outcome.currentStatus(), outcome.currentPhase(), outcome.frozenAfter()),
                    parties(item.targetId()), occurredAt));
        }
        return outcomes;
    }

    @Override
    public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction, ExecutionContext context,
                                                        long caseId, CaseRecords.Enforcement recorded,
                                                        String resolution, String basisRef, String reason,
                                                        Instant occurredAt) {
        if (!reverseSupported(recorded)) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该处置动作的反向执行尚未启用");
        }
        long transitionId;
        if ("trade_transition".equals(recorded.resultType())) {
            if (recorded.resultId() == null || recorded.resultId() <= 0) {
                throw freezeNotActive();
            }
            transitionId = recorded.resultId();
        } else if ("trade".equals(recorded.resultType())) {
            transitionId = trades.legacyFreezeTransition(caseId, recorded.targetId());
        } else {
            throw freezeNotActive();
        }
        var outcome = trades.liftFreezeLocked(transaction, caseId, recorded.targetId(), transitionId, basisRef,
                reason);
        trades.publishLocked(transaction, caseId, recorded.targetId(), "lift_trade_freeze", outcome, reason);
        var remaining = outcome.frozenAfter() ? List.of("trade_freeze") : List.<String>of();
        return List.of(new CaseRecords.EnforcementOutcome(recorded.enforcementId() + "-lift",
                "lift_trade_freeze", "trade", recorded.targetId(), "trade_transition",
                outcome.transitionId(), "applied",
                state(outcome.previousStatus(), outcome.previousPhase(), outcome.frozenBefore()),
                state(outcome.currentStatus(), outcome.currentPhase(), outcome.frozenAfter()),
                parties(recorded.targetId()), occurredAt, remaining));
    }

    @Override
    public LockPlan reversePlan(ExecutionContext context, long caseId, CaseRecords.Enforcement recorded,
                                String resolution) {
        if (!reverseSupported(recorded)) {
            return new LockPlan(java.util.Map.of(), Set.of());
        }
        return trades.prepare(actor(context), recorded.targetId(), caseId, false).lockPlan();
    }

    @Override
    public SubjectPlan reverseLockCallbacks(ExecutionContext context, long caseId,
                                            CaseRecords.Enforcement recorded, String resolution) {
        if (!reverseSupported(recorded)) {
            return SubjectPlan.empty();
        }
        var prepared = trades.prepare(actor(context), recorded.targetId(), caseId, false);
        return callbacks(prepared, recorded.targetId());
    }

    private SubjectPlan callbacks(TradePorts.CaseEnforcementPlan prepared, long tradeId) {
        var subjects = SubjectPlan.empty();
        for (var entry : prepared.lockPlan().accounts().entrySet()) {
            subjects = subjects.merge(SubjectPlan.account(entry.getKey(), entry.getValue()));
        }
        var plan = prepared.lockPlan();
        if (prepared.productId() != null) {
            var productKey = key(plan, LockPlan.Domain.PRODUCT);
            subjects = subjects.merge(SubjectPlan.resource(productKey,
                    transaction -> trades.lockCaseProductRow(transaction, prepared.productId())));
        }
        var tradeKey = key(plan, LockPlan.Domain.TRADE);
        subjects = subjects.merge(SubjectPlan.resource(tradeKey,
                transaction -> trades.lockTradeRow(transaction, tradeId)));
        var conversationKey = key(plan, LockPlan.Domain.TRADE_CONVERSATION);
        subjects = subjects.merge(SubjectPlan.resource(conversationKey,
                transaction -> trades.lockConversationRow(transaction, prepared.conversationId())));
        return subjects;
    }

    private List<Long> parties(long tradeId) {
        return participation.findConversationAccess(tradeId)
                .map(access -> new TreeSet<>(List.of(access.buyerId(), access.sellerId())).stream().toList())
                .orElseGet(List::of);
    }

    private static LockPlan.Key key(LockPlan plan, LockPlan.Domain domain) {
        return plan.resources().stream().filter(key -> key.domain() == domain).findFirst()
                .orElseThrow(() -> new IllegalStateException("Prepared trade plan lacks " + domain));
    }

    private static boolean adjust(CaseRecords.EnforcementInstruction item) {
        return "adjust_trade_status".equals(item.action());
    }

    private static boolean reverseSupported(CaseRecords.Enforcement recorded) {
        return "freeze_trade".equals(recorded.action()) && "trade".equals(recorded.targetType());
    }

    private static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    private static String state(String status, String phase, boolean frozen) {
        return "status=" + status + ",phase=" + (phase == null ? "" : phase) + ",frozen=" + frozen;
    }

    private static void requireSupported(CaseRecords.EnforcementInstruction item) {
        if (!SUPPORTED.contains(item.action()) || !"trade".equals(item.targetType())) {
            throw unavailable();
        }
    }

    private static BusinessError unavailable() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该处置动作的正式执行由 S4-01 提供");
    }

    private static BusinessError freezeNotActive() {
        return new BusinessError("TRADE_FREEZE_NOT_ACTIVE", 409, "原交易冻结已解除或不存在");
    }
}
