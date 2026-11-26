package io.github.iy88.project1.api.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/** One batch plan and one dispatch table for trade, subject and content enforcement items. */
class CoordinatingCaseEnforcementTests {
    private static final long CASE = 41L;
    private static final long NOW_MILLIS = 1_000L;
    private static final Instant NOW = Instant.ofEpochMilli(NOW_MILLIS);
    private static final ExecutionContext CONTEXT = new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, "903", UUID.randomUUID(), null, 1L, "test");

    private final TradeCaseEnforcement trades = mock(TradeCaseEnforcement.class);
    private final SubjectCaseEnforcement subjects = mock(SubjectCaseEnforcement.class);
    private final ContentCaseEnforcement contents = mock(ContentCaseEnforcement.class);
    private final CoordinatingCaseEnforcement coordinator = new CoordinatingCaseEnforcement(trades, subjects,
            contents);
    private final WriteTransaction transaction = mock(WriteTransaction.class);

    @Test
    void onePlanRoutesEachActionToItsOwnerWithoutDuplicatingAKey() {
        var content = instruction("remove_content", "comment", 501L);
        var subject = instruction("withdraw_public_access", "product", 701L);
        var trade = instruction("freeze_trade", "trade", 801L);
        when(trades.productForTrade(801L)).thenReturn(701L);
        supportContent("remove_content");
        supportSubject("withdraw_public_access");
        var productKey = new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(701L));
        var commentKey = new LockPlan.Key(LockPlan.Domain.PRODUCT_DETAIL, List.of(501L));
        var tradeKey = new LockPlan.Key(LockPlan.Domain.TRADE, List.of(801L));
        when(trades.plan(CONTEXT, CASE, List.of(trade))).thenReturn(
                new LockPlan(Map.of(), Set.of(productKey, tradeKey)));
        when(subjects.plan(CASE, List.of(subject))).thenReturn(
                new LockPlan(Map.of(), Set.of(productKey)));
        when(contents.plan(CASE, List.of(content))).thenReturn(
                new LockPlan(Map.of(), Set.of(productKey, commentKey)));

        var plan = coordinator.plan(CONTEXT, CASE, List.of(content, subject, trade));

        assertThat(plan.resources()).containsExactlyInAnyOrder(productKey, commentKey, tradeKey);
        verify(trades).plan(CONTEXT, CASE, List.of(trade));
        verify(subjects).plan(CASE, List.of(subject));
        verify(contents).plan(CASE, List.of(content));
    }

    @Test
    void lockCallbacksMergeTheSameThreeOwners() {
        var content = instruction("remove_content", "comment", 501L);
        var subject = instruction("withdraw_public_access", "product", 701L);
        var trade = instruction("freeze_trade", "trade", 801L);
        when(trades.productForTrade(801L)).thenReturn(701L);
        supportContent("remove_content");
        supportSubject("withdraw_public_access");
        var contentCallbacks = SubjectPlan.resource(new LockPlan.Key(LockPlan.Domain.PRODUCT_DETAIL, List.of(501L)),
                ignored -> {
                });
        var subjectCallbacks = SubjectPlan.resource(new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(701L)),
                ignored -> {
                });
        var tradeCallbacks = SubjectPlan.resource(new LockPlan.Key(LockPlan.Domain.TRADE, List.of(801L)),
                ignored -> {
                });
        when(trades.lockCallbacks(CONTEXT, CASE, List.of(trade))).thenReturn(tradeCallbacks);
        when(subjects.lockCallbacks(CASE, List.of(subject))).thenReturn(subjectCallbacks);
        when(contents.lockCallbacks(CASE, List.of(content))).thenReturn(contentCallbacks);

        var callbacks = coordinator.lockCallbacks(CONTEXT, CASE, List.of(content, subject, trade));

        assertThat(callbacks.lockPlan().resources()).containsExactlyInAnyOrder(
                new LockPlan.Key(LockPlan.Domain.PRODUCT_DETAIL, List.of(501L)),
                new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(701L)),
                new LockPlan.Key(LockPlan.Domain.TRADE, List.of(801L)));
        verify(trades).lockCallbacks(CONTEXT, CASE, List.of(trade));
        verify(subjects).lockCallbacks(CASE, List.of(subject));
        verify(contents).lockCallbacks(CASE, List.of(content));
    }

    @Test
    void executeDispatchesEachSingleItemToItsOwnerAndKeepsOutcomeOrder() {
        var content = instruction("remove_content", "comment", 501L);
        var subject = instruction("withdraw_public_access", "product", 701L);
        var trade = instruction("freeze_trade", "trade", 801L);
        when(trades.productForTrade(801L)).thenReturn(701L);
        supportContent("remove_content");
        supportSubject("withdraw_public_access");
        var contentOutcome = outcome(content, "comment", 501L);
        var subjectOutcome = outcome(subject, "product", 701L);
        var tradeOutcome = outcome(trade, "trade", 801L);
        when(contents.execute(transaction, CASE, "reason", "case:41", List.of(content), NOW))
                .thenReturn(List.of(contentOutcome));
        when(subjects.execute(transaction, CASE, "reason", "case:41", List.of(subject), NOW))
                .thenReturn(List.of(subjectOutcome));
        when(trades.execute(transaction, CONTEXT, CASE, "reason", "case:41", List.of(trade), NOW))
                .thenReturn(List.of(tradeOutcome));

        var outcomes = coordinator.execute(transaction, CONTEXT, CASE, "reason", "case:41",
                List.of(content, subject, trade), NOW);

        assertThat(outcomes).containsExactly(contentOutcome, subjectOutcome, tradeOutcome);
    }

    @Test
    void reversalRoutesByRecordedAction() {
        var recorded = new CaseRecords.Enforcement("enf-1", CASE, "remove_content", "comment", 501L, "case:41",
                903L, NOW, "product_comment", 501L, "applied", "published", "removed_by_admin",
                List.of(901L), null, null, NOW, null);
        supportContent("remove_content");
        var reversed = outcome(instruction("remove_content", "comment", 501L), "comment", 501L);
        when(contents.reverse(transaction, CASE, recorded, "case:41", "restore", NOW))
                .thenReturn(List.of(reversed));
        when(contents.reversePlan(CASE, recorded)).thenReturn(new LockPlan(Map.of(), Set.of()));
        when(contents.reverseLockCallbacks(CASE, recorded)).thenReturn(SubjectPlan.empty());

        assertThat(coordinator.reverse(transaction, CONTEXT, CASE, recorded, "revoke", "case:41",
                "restore", NOW)).containsExactly(reversed);
        assertThat(coordinator.reversePlan(CONTEXT, CASE, recorded, "revoke").resources()).isEmpty();
        assertThat(coordinator.reverseLockCallbacks(CONTEXT, CASE, recorded, "revoke").lockPlan().resources())
                .isEmpty();
    }

    private void supportContent(String action) {
        when(contents.supports(anyString())).thenReturn(false);
        when(contents.supports(action)).thenReturn(true);
    }

    private void supportSubject(String action) {
        when(subjects.supports(anyString())).thenReturn(false);
        when(subjects.supports(action)).thenReturn(true);
    }

    private static CaseRecords.EnforcementInstruction instruction(String action, String targetType, long targetId) {
        return new CaseRecords.EnforcementInstruction("enf-" + action, action, targetType, targetId, null);
    }

    private static CaseRecords.EnforcementOutcome outcome(CaseRecords.EnforcementInstruction item,
                                                          String targetType, long targetId) {
        return new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(), targetType, targetId,
                targetType + "_result", targetId, "applied", "before", "after", List.of(), NOW);
    }
}
