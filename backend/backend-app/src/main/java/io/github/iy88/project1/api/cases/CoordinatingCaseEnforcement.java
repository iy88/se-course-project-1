package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Production case-enforcement assembly. Direct trade actions stay with
 * {@link TradeCaseEnforcement}; account restrictions and product display restrictions are handled
 * by {@link SubjectCaseEnforcement}. Both handlers contribute to one merged batch plan and one
 * ordered write transaction, so a failure in any subject rolls back the whole decision.
 */
final class CoordinatingCaseEnforcement implements CasePorts.Enforcement {
    private final TradeCaseEnforcement trades;
    private final SubjectCaseEnforcement subjects;

    CoordinatingCaseEnforcement(TradeCaseEnforcement trades, SubjectCaseEnforcement subjects) {
        this.trades = Objects.requireNonNull(trades);
        this.subjects = Objects.requireNonNull(subjects);
    }

    @Override
    public LockPlan plan(ExecutionContext context, long caseId,
                         List<CaseRecords.EnforcementInstruction> instructions) {
        var plan = new LockPlan(Map.of(), Set.of());
        var tradeItems = instructions.stream().filter(item -> !subjects.supports(item.action())).toList();
        var subjectItems = instructions.stream().filter(item -> subjects.supports(item.action())).toList();
        if (!tradeItems.isEmpty()) {
            plan = plan.merge(trades.plan(context, caseId, tradeItems));
        }
        if (!subjectItems.isEmpty()) {
            plan = plan.merge(subjects.plan(caseId, subjectItems));
        }
        return plan;
    }

    @Override
    public SubjectPlan lockCallbacks(ExecutionContext context, long caseId,
                                     List<CaseRecords.EnforcementInstruction> instructions) {
        var callbacks = SubjectPlan.empty();
        var tradeItems = instructions.stream().filter(item -> !subjects.supports(item.action())).toList();
        var subjectItems = instructions.stream().filter(item -> subjects.supports(item.action())).toList();
        if (!tradeItems.isEmpty()) {
            callbacks = callbacks.merge(trades.lockCallbacks(context, caseId, tradeItems));
        }
        if (!subjectItems.isEmpty()) {
            callbacks = callbacks.merge(subjects.lockCallbacks(caseId, subjectItems));
        }
        return callbacks;
    }

    @Override
    public List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction, ExecutionContext context,
                                                        long caseId, String reason, String basisRef,
                                                        List<CaseRecords.EnforcementInstruction> instructions,
                                                        Instant occurredAt) {
        var outcomes = new ArrayList<CaseRecords.EnforcementOutcome>();
        for (var item : instructions) {
            var single = List.of(item);
            outcomes.addAll(subjects.supports(item.action())
                    ? subjects.execute(transaction, caseId, reason, basisRef, single, occurredAt)
                    : trades.execute(transaction, context, caseId, reason, basisRef, single, occurredAt));
        }
        return outcomes;
    }

    @Override
    public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction, ExecutionContext context,
                                                        long caseId, CaseRecords.Enforcement recorded,
                                                        String resolution, String basisRef, String reason,
                                                        Instant occurredAt) {
        if (subjects.supports(recorded.action())) {
            return subjects.reverse(transaction, caseId, recorded, basisRef, reason, occurredAt);
        }
        return trades.reverse(transaction, context, caseId, recorded, resolution, basisRef, reason, occurredAt);
    }

    @Override
    public LockPlan reversePlan(ExecutionContext context, long caseId, CaseRecords.Enforcement recorded,
                                String resolution) {
        if (subjects.supports(recorded.action())) {
            return subjects.reversePlan(caseId, recorded);
        }
        return trades.reversePlan(context, caseId, recorded, resolution);
    }

    @Override
    public SubjectPlan reverseLockCallbacks(ExecutionContext context, long caseId, CaseRecords.Enforcement recorded,
                                            String resolution) {
        if (subjects.supports(recorded.action())) {
            return subjects.reverseLockCallbacks(caseId, recorded);
        }
        return trades.reverseLockCallbacks(context, caseId, recorded, resolution);
    }
}
