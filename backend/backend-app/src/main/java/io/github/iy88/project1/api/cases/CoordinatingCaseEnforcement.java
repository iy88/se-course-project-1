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
 * by {@link SubjectCaseEnforcement}; comment and evaluation removal is handled by
 * {@link ContentCaseEnforcement}. All handlers contribute to one merged batch plan and one ordered
 * write transaction, so a failure in any subject rolls back the whole decision.
 */
final class CoordinatingCaseEnforcement implements CasePorts.Enforcement {
    private final TradeCaseEnforcement trades;
    private final SubjectCaseEnforcement subjects;
    private final ContentCaseEnforcement contents;

    CoordinatingCaseEnforcement(TradeCaseEnforcement trades, SubjectCaseEnforcement subjects,
                                ContentCaseEnforcement contents) {
        this.trades = Objects.requireNonNull(trades);
        this.subjects = Objects.requireNonNull(subjects);
        this.contents = Objects.requireNonNull(contents);
    }

    @Override
    public LockPlan plan(ExecutionContext context, long caseId,
                         List<CaseRecords.EnforcementInstruction> instructions) {
        var plan = new LockPlan(Map.of(), Set.of());
        var contentItems = instructions.stream().filter(item -> contents.supports(item.action())).toList();
        var otherItems = instructions.stream().filter(item -> !contents.supports(item.action())).toList();
        var tradeItems = otherItems.stream().filter(item -> !subjects.supports(item.action())).toList();
        var subjectItems = otherItems.stream().filter(item -> subjects.supports(item.action())).toList();
        if (!tradeItems.isEmpty()) {
            plan = plan.merge(trades.plan(context, caseId, tradeItems));
        }
        if (!subjectItems.isEmpty()) {
            plan = plan.merge(subjects.plan(caseId, subjectItems));
        }
        if (!contentItems.isEmpty()) {
            plan = plan.merge(contents.plan(caseId, contentItems));
        }
        return plan;
    }

    @Override
    public SubjectPlan lockCallbacks(ExecutionContext context, long caseId,
                                     List<CaseRecords.EnforcementInstruction> instructions) {
        var callbacks = SubjectPlan.empty();
        var contentItems = instructions.stream().filter(item -> contents.supports(item.action())).toList();
        var otherItems = instructions.stream().filter(item -> !contents.supports(item.action())).toList();
        var tradeItems = otherItems.stream().filter(item -> !subjects.supports(item.action())).toList();
        var subjectItems = otherItems.stream().filter(item -> subjects.supports(item.action())).toList();
        if (!tradeItems.isEmpty()) {
            callbacks = callbacks.merge(trades.lockCallbacks(context, caseId, tradeItems));
        }
        if (!subjectItems.isEmpty()) {
            callbacks = callbacks.merge(subjects.lockCallbacks(caseId, subjectItems));
        }
        if (!contentItems.isEmpty()) {
            callbacks = callbacks.merge(contents.lockCallbacks(caseId, contentItems));
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
            if (contents.supports(item.action())) {
                outcomes.addAll(contents.execute(transaction, caseId, reason, basisRef, single, occurredAt));
            } else if (subjects.supports(item.action())) {
                outcomes.addAll(subjects.execute(transaction, caseId, reason, basisRef, single, occurredAt));
            } else {
                outcomes.addAll(trades.execute(transaction, context, caseId, reason, basisRef, single,
                        occurredAt));
            }
        }
        return outcomes;
    }

    @Override
    public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction, ExecutionContext context,
                                                        long caseId, CaseRecords.Enforcement recorded,
                                                        String resolution, String basisRef, String reason,
                                                        Instant occurredAt) {
        if (contents.supports(recorded.action())) {
            return contents.reverse(transaction, caseId, recorded, basisRef, reason, occurredAt);
        }
        if (subjects.supports(recorded.action())) {
            return subjects.reverse(transaction, caseId, recorded, basisRef, reason, occurredAt);
        }
        return trades.reverse(transaction, context, caseId, recorded, resolution, basisRef, reason, occurredAt);
    }

    @Override
    public LockPlan reversePlan(ExecutionContext context, long caseId, CaseRecords.Enforcement recorded,
                                String resolution) {
        if (contents.supports(recorded.action())) {
            return contents.reversePlan(caseId, recorded);
        }
        if (subjects.supports(recorded.action())) {
            return subjects.reversePlan(caseId, recorded);
        }
        return trades.reversePlan(context, caseId, recorded, resolution);
    }

    @Override
    public SubjectPlan reverseLockCallbacks(ExecutionContext context, long caseId, CaseRecords.Enforcement recorded,
                                            String resolution) {
        if (contents.supports(recorded.action())) {
            return contents.reverseLockCallbacks(caseId, recorded);
        }
        if (subjects.supports(recorded.action())) {
            return subjects.reverseLockCallbacks(caseId, recorded);
        }
        return trades.reverseLockCallbacks(context, caseId, recorded, resolution);
    }
}
