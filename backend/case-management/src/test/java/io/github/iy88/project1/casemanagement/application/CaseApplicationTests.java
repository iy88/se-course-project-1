package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseSettings;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Lifecycle rules of reports, claims, inquiries, appeals, decisions and closing. */
class CaseApplicationTests {
    private static final long REPORTER = 11L;
    private static final long RELATED = 21L;
    private static final long MANAGER = 31L;
    private static final long OTHER_MANAGER = 32L;
    private static final long CASE_ID = 41L;
    private static final long THREAD_ID = 71L;
    private static final long TRADE_ID = 900L;
    private static final Instant NOW = Instant.parse("2026-11-24T00:00:00Z");
    private static final JsonMapper JSON = JsonMapper.builder().build();

    @Test
    void submitsANewReportAndReusesTheOpenOneAsSupplement() {
        var harness = harness(pending());
        var report = new CaseCommands.Report(new CaseCommands.Target("account", RELATED, null, null),
                "虚假信息", "补充说明", List.of());

        var created = harness.application.submit(context(REPORTER), "key-1", report);
        assertThat(created.status()).isEqualTo(201);
        assertThat(created.data().get("case_id").asString()).isEqualTo("41");
        assertThat(created.data().get("reused").asBoolean()).isFalse();
        verify(harness.store).openReportIfAbsent(report.target(), REPORTER, "虚假信息", NOW);

        when(harness.store.findOpenReport(REPORTER, report.target())).thenReturn(Optional.of(pending()));
        when(harness.store.lock(harness.transaction, CASE_ID)).thenReturn(pending());
        var reused = harness.application.submit(context(REPORTER), "key-2", report);
        assertThat(reused.status()).isEqualTo(200);
        assertThat(reused.data().get("reused").asBoolean()).isTrue();
        verify(harness.store, org.mockito.Mockito.times(1))
                .openReportIfAbsent(eq(report.target()), eq(REPORTER), anyString(), any());
    }

    @Test
    void claimIsUniqueAndAlreadyClaimedForTheSameManager() {
        var harness = harness(pending());
        when(harness.store.claim(CASE_ID, MANAGER, NOW)).thenReturn(claimed());

        var claimed = harness.application.claim(context(MANAGER), "claim-1", CASE_ID);
        assertThat(claimed.data().get("already_claimed").asBoolean()).isFalse();
        assertThat(claimed.data().get("claimed_manager_id").asString()).isEqualTo("31");

        when(harness.store.lock(harness.transaction, CASE_ID)).thenReturn(claimed());
        var repeated = harness.application.claim(context(MANAGER), "claim-2", CASE_ID);
        assertThat(repeated.data().get("already_claimed").asBoolean()).isTrue();

        when(harness.store.lock(harness.transaction, CASE_ID)).thenReturn(claimedBy(OTHER_MANAGER));
        assertThatThrownBy(() -> harness.application.claim(context(MANAGER), "claim-3", CASE_ID))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_ALREADY_CLAIMED"));
    }

    @Test
    void inquiryRequiresTheClaimingManagerAndCreatesAThreadMessage() {
        var harness = harness(claimed());
        when(harness.threads.ensure(harness.transaction, CASE_ID, RELATED)).thenReturn(THREAD_ID);

        var result = harness.application.inquire(context(MANAGER), "inq-1", CASE_ID,
                new CaseCommands.Inquiry(RELATED, "请说明交易过程"));
        assertThat(result.status()).isEqualTo(201);
        assertThat(result.data().get("inquiry_action_id").asString()).isEqualTo("101");
        assertThat(result.data().get("case_message_id").asString()).isEqualTo("11");
        verify(harness.notifications).create(eq(harness.transaction), eq(CaseVocabulary.EVENT_INQUIRY_CREATED),
                eq("case:41:inquiry:101"), any(), eq(Set.of(RELATED)), any(), eq(NOW));

        when(harness.store.lock(harness.transaction, CASE_ID)).thenReturn(claimedBy(OTHER_MANAGER));
        assertThatThrownBy(() -> harness.application.inquire(context(MANAGER), "inq-2", CASE_ID,
                new CaseCommands.Inquiry(RELATED, "请说明")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("NOT_CASE_MANAGER"));
    }

    @Test
    void appealMustBeWithinTheWindowAndOnlyOnce() {
        var harness = harness(decided());
        when(harness.store.appealEligibility(CASE_ID, RELATED))
                .thenReturn(Optional.of(new CaseRecords.AppealEligibility(CASE_ID, RELATED,
                        NOW.plusSeconds(600), "case:41")));
        when(harness.store.decideIfClaimed(anyLong(), anyString(), anyString(), anyLong(), any()))
                .thenReturn(true);

        var submitted = harness.application.postMessage(context(RELATED), "ap-1", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_APPEAL, "请求复核", null, null, null, null));
        assertThat(submitted.status()).isEqualTo(201);

        when(harness.store.hasPendingAppeal(CASE_ID, RELATED)).thenReturn(true);
        when(harness.store.action(CASE_ID, 102L)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));
        assertThatThrownBy(() -> harness.application.postMessage(context(RELATED), "ap-2", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_APPEAL, "再次", null, null, null, null)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));

        when(harness.store.appealEligibility(CASE_ID, RELATED))
                .thenReturn(Optional.of(new CaseRecords.AppealEligibility(CASE_ID, RELATED,
                        NOW.minusSeconds(1), "case:41")));
        assertThatThrownBy(() -> harness.application.postMessage(context(RELATED), "ap-3", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_APPEAL, "过期", null, null, null, null)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_APPEAL_WINDOW_ENDED"));
    }

    @Test
    void closingWaitsForTheWindowAndForEveryAppeal() {
        var harness = harness(decided());
        when(harness.store.appealEligibilities(CASE_ID))
                .thenReturn(List.of(new CaseRecords.AppealEligibility(CASE_ID, RELATED, NOW.plusSeconds(60),
                        "case:41")));
        assertThatThrownBy(() -> harness.application.close(context(MANAGER), "close-1", CASE_ID))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_APPEAL_WINDOW_OPEN"));

        when(harness.store.appealEligibilities(CASE_ID))
                .thenReturn(List.of(new CaseRecords.AppealEligibility(CASE_ID, RELATED, NOW.minusSeconds(60),
                        "case:41")));
        when(harness.store.latestPendingAppeal(CASE_ID)).thenReturn(Optional.of(new CaseRecords.Action(103,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 13L,
                RELATED, null, null, null, null, null)));
        assertThatThrownBy(() -> harness.application.close(context(MANAGER), "close-2", CASE_ID))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_APPEAL_PENDING"));

        when(harness.store.latestPendingAppeal(CASE_ID)).thenReturn(Optional.empty());
        when(harness.store.archive(CASE_ID, NOW)).thenReturn(archived());
        when(harness.store.relatedAccountIds(CASE_ID)).thenReturn(List.of(RELATED));
        var closed = harness.application.close(context(MANAGER), "close-3", CASE_ID);
        assertThat(closed.status()).isEqualTo(200);
        assertThat(closed.data().get("archived_at").asString()).isEqualTo(NOW.toString());
        verify(harness.threads).archive(harness.transaction, CASE_ID, RELATED);
    }

    @Test
    void publishRequiresAClosedReportAndNotifiesTheReporter() {
        var harness = harness(decided());
        harness.facts.set(archived());
        var result = harness.application.publish(context(MANAGER), "pub-1", CASE_ID,
                new CaseCommands.Publish("认定违规", "依据证据"));
        assertThat(result.status()).isEqualTo(200);
        verify(harness.notifications).create(eq(harness.transaction), eq(CaseVocabulary.EVENT_RESULT_PUBLISHED),
                eq("case:41:result_published"), any(), eq(Set.of(REPORTER)), any(), eq(NOW));

        var alreadyPublished = published(archived());
        harness.facts.set(alreadyPublished);
        when(harness.store.lock(harness.transaction, CASE_ID)).thenReturn(alreadyPublished);
        assertThatThrownBy(() -> harness.application.publish(context(MANAGER), "pub-2", CASE_ID,
                new CaseCommands.Publish("再次", "再次")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));
    }

    @Test
    void contentRemovalDecisionNotifiesOnlyTheExactAuthor() {
        var enforcement = mock(CasePorts.Enforcement.class);
        var outcome = new CaseRecords.EnforcementOutcome("enf-1", "remove_content", "comment", 500L,
                "product_comment", 500L, "applied", "published", "removed_by_admin", List.of(RELATED), NOW);
        when(enforcement.plan(any(), anyLong(), anyList())).thenReturn(new LockPlan(Map.of(), Set.of()));
        when(enforcement.lockCallbacks(any(), anyLong(), anyList())).thenReturn(SubjectPlan.empty());
        when(enforcement.execute(any(), any(), anyLong(), anyString(), anyString(), anyList(), any()))
                .thenReturn(List.of(outcome));
        var harness = harness(claimed(), enforcement);
        when(harness.store.decideIfClaimed(anyLong(), anyString(), anyString(), anyLong(), any()))
                .thenAnswer(invocation -> {
                    harness.facts.set(decide(harness.facts.get()));
                    return true;
                });

        var result = harness.application.decide(context(MANAGER), "decide-content", CASE_ID,
                new CaseCommands.Decision(CaseVocabulary.VIOLATION, "认定违规", List.of(),
                        List.of(new CaseCommands.Enforcement("remove_content", "comment", 500L, null))));

        assertThat(result.status()).isEqualTo(201);
        verify(harness.notifications).create(eq(harness.transaction), eq(CaseVocabulary.EVENT_CONTENT_REMOVED),
                eq("case:41:enf-1:removed"), any(), eq(Set.of(RELATED)), any(), eq(NOW));
        verify(harness.threads).ensure(harness.transaction, CASE_ID, RELATED);
    }

    @Test
    void appealRevocationUsesTheExecutionPortAndLiftsTheRecordedEnforcement() {
        var recorded = new CaseRecords.Enforcement("enf-1", CASE_ID, "freeze_trade", "trade", 900L, "case:41",
                MANAGER, NOW, "trade", 900L, "applied", "active", "frozen", List.of(RELATED), null, null, NOW, null);
        var reversing = new CasePorts.Enforcement() {
            @Override
            public LockPlan plan(ExecutionContext context, long caseId,
                                 List<CaseRecords.EnforcementInstruction> instructions) {
                return new LockPlan(Map.of(), Set.of());
            }

            @Override
            public List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId,
                                                                String reason, String basisRef,
                                                                List<CaseRecords.EnforcementInstruction> instructions,
                                                                Instant occurredAt) {
                return List.of();
            }

            @Override
            public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId,
                                                                CaseRecords.Enforcement enforcement,
                                                                String resolution, String basisRef, String reason,
                                                                Instant occurredAt) {
                return List.of(new CaseRecords.EnforcementOutcome("enf-1-lift", "lift_trade_freeze", "trade",
                        900L, "trade", 900L, "applied", "frozen", "active", List.of(RELATED), occurredAt));
            }
        };
        var harness = harness(decided(), reversing);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recorded));
        when(harness.store.appealOf(CASE_ID, RELATED)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));
        when(harness.store.action(CASE_ID, 102L)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));

        var resolved = harness.application.postMessage(context(MANAGER), "revoke-1", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "撤销处置", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据", "enf-1"));
        assertThat(resolved.status()).isEqualTo(201);
        verify(harness.store).markEnforcementLifted(eq(CASE_ID), eq("enf-1"), eq(MANAGER), eq("依据"), eq(NOW));
        verify(harness.store, org.mockito.Mockito.times(1)).addEnforcement(any());
    }

    @Test
    void appealRevocationWithoutAnExecutionPortFailsClosed() {
        var harness = harness(decided());
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(new CaseRecords.Enforcement(
                "enf-1", CASE_ID, "freeze_trade", "trade", 900L, "case:41", MANAGER, NOW, "trade", 900L,
                "applied", "active", "frozen", List.of(RELATED), null, null, NOW, null)));
        when(harness.store.appealOf(CASE_ID, RELATED)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));
        when(harness.store.action(CASE_ID, 102L)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));
        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "revoke-2", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "撤销处置", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据", "enf-1")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("DEPENDENCY_UNAVAILABLE"));
    }

    @Test
    void revokeRequiresTheExplicitOriginalEnforcementSelection() {
        var harness = harness(decided());
        stubAppeal(harness);

        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "revoke-no-id", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "撤销处置", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        verify(harness.store, never()).markEnforcementLifted(anyLong(), anyString(), anyLong(), anyString(), any());
    }

    @Test
    void selectedOriginalMustBelongToTheAppellantAndStillBeActive() {
        var recorded = recordedEnforcement();
        var harness = harness(decided(), adjusting());
        stubAppeal(harness);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(new CaseRecords.Enforcement(
                "enf-1", CASE_ID, "restrict_account", "account", RELATED, "case:41", MANAGER, NOW,
                "account_restriction", RELATED, "applied", "active", "restricted", List.of(99L), null, null,
                NOW, null)));

        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "revoke-other", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "撤销处置", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据", "enf-1")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));

        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recorded));
        when(harness.store.lift(CASE_ID, "enf-1")).thenReturn(Optional.of(new CaseRecords.Lift(NOW, MANAGER)));
        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "revoke-lifted", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "撤销处置", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据", "enf-1")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));
    }

    @Test
    void revokeOnlyLiftsTheSelectedOriginalAndLeavesOtherEnforcementsActive() {
        var harness = harness(decided(), adjusting());
        stubAppeal(harness);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recordedEnforcement()));
        when(harness.store.enforcement(CASE_ID, "enf-2")).thenReturn(Optional.of(new CaseRecords.Enforcement(
                "enf-2", CASE_ID, "withdraw_public_access", "product", 500L, "case:41", MANAGER, NOW,
                "product", 500L, "applied", "public", "restricted", List.of(RELATED), null, null, NOW, null)));

        var result = harness.application.postMessage(context(MANAGER), "revoke-selected", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "只撤销冻结", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据", "enf-1"));

        assertThat(result.status()).isEqualTo(201);
        verify(harness.store).markEnforcementLifted(eq(CASE_ID), eq("enf-1"), eq(MANAGER), eq("依据"), eq(NOW));
        verify(harness.store, never()).markEnforcementLifted(eq(CASE_ID), eq("enf-2"), anyLong(), anyString(), any());
        verify(harness.store, org.mockito.Mockito.times(1)).addEnforcement(any());
    }

    @Test
    void selectedOriginalFromAnotherCaseIsHiddenAndNeverReversed() {
        var enforcement = mock(CasePorts.Enforcement.class);
        var harness = harness(decided(), enforcement);
        stubAppeal(harness);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(new CaseRecords.Enforcement(
                "enf-1", CASE_ID + 1, "freeze_trade", "trade", 900L, "case:42", MANAGER, NOW,
                "trade_transition", 55L, "applied", "active", "frozen", List.of(RELATED), null, null, NOW, null)));

        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "revoke-cross-case", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "撤销处置", null, 102L,
                        CaseVocabulary.RESOLUTION_REVOKE, "依据", "enf-1")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
        verify(enforcement, never()).reverse(any(), any(), anyLong(), any(), anyString(), anyString(), anyString(),
                any());
        verify(harness.store, never()).markEnforcementLifted(anyLong(), anyString(), anyLong(), anyString(), any());
        verify(harness.store, never()).addAction(any());
        verify(harness.threads, never()).append(any(), anyLong(), anyLong(), anyString(), anyString(), anyLong(),
                anyString());
    }

    @Test
    void failedAdjustmentKeepsTheOriginalAndDoesNotWriteTheManagerReply() {
        var enforcement = mock(CasePorts.Enforcement.class);
        when(enforcement.plan(any(), eq(CASE_ID), any())).thenReturn(casePlan());
        when(enforcement.lockCallbacks(any(), eq(CASE_ID), any())).thenReturn(SubjectPlan.empty());
        when(enforcement.reverseLockCallbacks(any(), eq(CASE_ID), any(), anyString()))
                .thenReturn(SubjectPlan.empty());
        when(enforcement.reverse(any(), any(), eq(CASE_ID), any(), anyString(), anyString(), anyString(), any()))
                .thenReturn(List.of(new CaseRecords.EnforcementOutcome("enf-1-reversed", "lift_trade_freeze",
                        "trade", 900L, "trade_transition", 55L, "applied", "frozen", "active", List.of(), NOW)));
        when(enforcement.execute(any(), any(), eq(CASE_ID), anyString(), anyString(), any(), any()))
                .thenThrow(new BusinessError("TRADE_TERMINAL", 409, "已结束交易保持终态"));
        var harness = harness(decided(), enforcement);
        stubAppeal(harness);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(new CaseRecords.Enforcement(
                "enf-1", CASE_ID, "freeze_trade", "trade", 900L, "case:41", MANAGER, NOW,
                "trade_transition", 55L, "applied", "frozen", "frozen", List.of(RELATED), null, null, NOW, null)));

        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "adjust-fails", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "调整处置", null, 102L,
                        CaseVocabulary.RESOLUTION_ADJUST, "依据", "enf-1",
                        List.of(new CaseCommands.Enforcement("adjust_trade_status", "trade", 900L, "in_progress")))))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));

        // The compensating row is written through the same transaction. Its absence from the final
        // state is proven by the rollback integration case; here the original must stay active and
        // no reply/lift fact may be committed.
        verify(enforcement).reverse(any(), any(), eq(CASE_ID), any(), anyString(), anyString(), anyString(), any());
        verify(enforcement).execute(any(), any(), eq(CASE_ID), anyString(), anyString(), any(), any());
        verify(harness.store, never()).markEnforcementLifted(anyLong(), anyString(), anyLong(), anyString(), any());
        verify(harness.store, never()).addAction(any());
        verify(harness.threads, never()).append(any(), anyLong(), anyLong(), anyString(), anyString(), anyLong(),
                anyString());
        verify(harness.notifications, never()).create(any(), anyString(), anyString(), any(), any(), any(), any());
    }

    @Test
    void upholdRejectsARevocationSelection() {
        var harness = harness(decided());
        stubAppeal(harness);
        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "uphold-fields", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "维持原决定", null, 102L,
                        CaseVocabulary.RESOLUTION_UPHOLD, "依据", "enf-1")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }

    @Test
    void adjustReversesThenAppliesTheConcreteReplacementInOneTransaction() {
        var recorded = new CaseRecords.Enforcement("enf-1", CASE_ID, "freeze_trade", "trade", 900L, "case:41",
                MANAGER, NOW, "trade_transition", 55L, "applied", "frozen", "frozen", List.of(RELATED), null,
                null, NOW, null);
        var harness = harness(decided(), adjusting());
        stubAppeal(harness);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recorded));

        var result = harness.application.postMessage(context(MANAGER), "adjust-1", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "调整处置", null, 102L,
                        CaseVocabulary.RESOLUTION_ADJUST, "依据", "enf-1",
                        List.of(new CaseCommands.Enforcement("adjust_trade_status", "trade", 900L, "terminated"))));

        assertThat(result.status()).isEqualTo(201);
        verify(harness.store).markEnforcementLifted(eq(CASE_ID), eq("enf-1"), eq(MANAGER), eq("依据"), eq(NOW));
        verify(harness.store, org.mockito.Mockito.times(2)).addEnforcement(any());
        verify(harness.store, org.mockito.Mockito.times(2)).addAction(any());
    }

    @Test
    void adjustRequiresAReplacementAndRejectsTerminalOriginals() {
        var harness = harness(decided(), adjusting());
        stubAppeal(harness);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recordedEnforcement()));

        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "adjust-empty", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "调整处置", null, 102L,
                        CaseVocabulary.RESOLUTION_ADJUST, "依据", "enf-1")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));

        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(new CaseRecords.Enforcement(
                "enf-1", CASE_ID, "adjust_trade_status", "trade", 900L, "case:41", MANAGER, NOW,
                "trade_transition", 55L, "applied", "completed", "completed", List.of(RELATED), null, null,
                NOW, null)));
        assertThatThrownBy(() -> harness.application.postMessage(context(MANAGER), "adjust-terminal", CASE_ID,
                new CaseCommands.Message(THREAD_ID, CaseVocabulary.KIND_MANAGER_REPLY, "调整处置", null, 102L,
                        CaseVocabulary.RESOLUTION_ADJUST, "依据", "enf-1",
                        List.of(new CaseCommands.Enforcement("adjust_trade_status", "trade", 900L, "terminated")))))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
    }

    private static void stubAppeal(Harness harness) {
        when(harness.store.appealOf(CASE_ID, RELATED)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));
        when(harness.store.action(CASE_ID, 102L)).thenReturn(Optional.of(new CaseRecords.Action(102,
                CASE_ID, CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, RELATED, NOW, 12L,
                RELATED, null, null, null, null, null)));
    }

    private static CasePorts.Enforcement adjusting() {
        return new CasePorts.Enforcement() {
            @Override
            public LockPlan plan(ExecutionContext context, long caseId,
                                 List<CaseRecords.EnforcementInstruction> instructions) {
                return new LockPlan(Map.of(), Set.of());
            }

            @Override
            public List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId,
                                                                String reason, String basisRef,
                                                                List<CaseRecords.EnforcementInstruction> instructions,
                                                                Instant occurredAt) {
                return instructions.stream().map(item -> new CaseRecords.EnforcementOutcome(
                        item.enforcementId(), item.action(), item.targetType(), item.targetId(),
                        "trade_transition", 56L, "applied", "frozen", "completed", List.of(RELATED),
                        occurredAt)).toList();
            }

            @Override
            public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId,
                                                                CaseRecords.Enforcement enforcement,
                                                                String resolution, String basisRef, String reason,
                                                                Instant occurredAt) {
                return List.of(new CaseRecords.EnforcementOutcome(enforcement.enforcementId() + "-lift",
                        "lift_trade_freeze", "trade", enforcement.targetId(), "trade_transition", 55L,
                        "applied", "frozen", "frozen", List.of(RELATED), occurredAt));
            }
        };
    }

    // ------------------------------------------------------------------ platform record evidence

    @Test
    void referencesTheReportedMessageWithoutDuplicatingOrReturningItsBody() {
        var harness = harness(messageCase());
        var reference = new CaseCommands.EvidenceReference("chat", 77L, 55L);
        when(harness.targets.requireReportedMessage(any(), eq("chat"), eq(77L), eq(55L)))
                .thenReturn(new CaseRecords.ReferencedMessage(55L, "chat", 77L, "account", RELATED,
                        "private message", NOW));
        when(harness.store.platformEvidence(CASE_ID, "message", 55L, "chat:77"))
                .thenReturn(Optional.empty());
        when(harness.store.addPlatformEvidence(CASE_ID, "message", 55L, "chat:77", MANAGER, NOW))
                .thenReturn(301L);

        var created = harness.application.referenceEvidence(context(MANAGER), "evidence-1", CASE_ID, reference);

        assertThat(created.status()).isEqualTo(201);
        assertThat(created.data().get("evidence_id").asString()).isEqualTo("301");
        assertThat(created.data().get("evidence_kind").asString()).isEqualTo("platform_record");
        assertThat(created.data().get("source_ref").get("resource_type").asString()).isEqualTo("message");
        assertThat(created.data().get("source_ref").get("resource_id").asString()).isEqualTo("55");
        assertThat(created.data().has("body")).isFalse();
        assertThat(created.data().has("message")).isFalse();
        verify(harness.store).addPlatformEvidence(CASE_ID, "message", 55L, "chat:77", MANAGER, NOW);

        when(harness.store.platformEvidence(CASE_ID, "message", 55L, "chat:77"))
                .thenReturn(Optional.of(new CaseRecords.Evidence(301L, CASE_ID,
                        CaseVocabulary.EVIDENCE_PLATFORM_RECORD, null, null, "message", 55L,
                        "chat:77", MANAGER, NOW)));
        var replay = harness.application.referenceEvidence(context(MANAGER), "evidence-2", CASE_ID, reference);
        assertThat(replay.status()).isEqualTo(200);
        assertThat(replay.data().get("reused").asBoolean()).isTrue();
        assertThat(replay.data().get("evidence_id").asString()).isEqualTo("301");
        verify(harness.store, org.mockito.Mockito.times(1))
                .addPlatformEvidence(CASE_ID, "message", 55L, "chat:77", MANAGER, NOW);
    }

    @Test
    void evidenceReferenceHidesOtherClaimantsAndRejectsOutOfScopeMessages() {
        var command = new CaseCommands.EvidenceReference("chat", 77L, 55L);
        var unclaimed = harness(claimedBy(OTHER_MANAGER));
        assertThatThrownBy(() -> unclaimed.application.referenceEvidence(context(MANAGER), "evidence-1",
                CASE_ID, command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
        verify(unclaimed.store, never()).addPlatformEvidence(anyLong(), anyString(), anyLong(), anyString(),
                anyLong(), any());

        var denied = harness(claimedBy(REPORTER));
        org.mockito.Mockito.doThrow(new BusinessError("ACTION_NOT_ALLOWED", 403, "无管理资格"))
                .when(denied.managers).requireManagerForWrite(any());
        assertThatThrownBy(() -> denied.application.referenceEvidence(context(REPORTER), "evidence-role",
                CASE_ID, command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));

        var wrongScope = harness(messageCase());
        when(wrongScope.targets.requireReportedMessage(any(), anyString(), anyLong(), anyLong()))
                .thenThrow(new BusinessError("EVIDENCE_OUT_OF_SCOPE", 422, "超出范围"));
        assertThatThrownBy(() -> wrongScope.application.referenceEvidence(context(MANAGER), "evidence-2",
                CASE_ID, command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("EVIDENCE_OUT_OF_SCOPE"));
    }

    // ------------------------------------------------------------------ lift

    @Test
    void liftReversesTheRecordedEnforcementAndReportsTheRestoredScope() {
        var reversing = new CasePorts.Enforcement() {
            @Override
            public LockPlan plan(ExecutionContext context, long caseId,
                                 List<CaseRecords.EnforcementInstruction> instructions) {
                return new LockPlan(Map.of(), Set.of());
            }

            @Override
            public List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId,
                                                                String reason, String basisRef,
                                                                List<CaseRecords.EnforcementInstruction> instructions,
                                                                Instant occurredAt) {
                return List.of();
            }

            @Override
            public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId,
                                                                CaseRecords.Enforcement enforcement,
                                                                String resolution, String basisRef, String reason,
                                                                Instant occurredAt) {
                return List.of(new CaseRecords.EnforcementOutcome("enf-1-lift", "lift_trade_freeze", "trade",
                        900L, "trade", 900L, "applied", "frozen", "active", List.of(RELATED), occurredAt));
            }
        };
        var harness = harness(decided(), reversing);
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recordedEnforcement()));
        when(harness.store.lift(CASE_ID, "enf-1")).thenReturn(Optional.empty(),
                Optional.of(new CaseRecords.Lift(NOW, MANAGER)));

        var result = harness.application.lift(context(MANAGER), "lift-1", CASE_ID, "enf-1", "解除封禁");
        assertThat(result.status()).isEqualTo(200);
        assertThat(result.data().get("lifted_by").asString()).isEqualTo("31");
        assertThat(result.data().get("restored_scope").get(0).asString()).isEqualTo("account:21");
        verify(harness.store).markEnforcementLifted(eq(CASE_ID), eq("enf-1"), eq(MANAGER), eq("解除封禁"), eq(NOW));
    }

    @Test
    void liftFailsClosedWithoutAnExecutionPort() {
        var harness = harness(decided());
        when(harness.store.enforcement(CASE_ID, "enf-1")).thenReturn(Optional.of(recordedEnforcement()));
        when(harness.store.lift(CASE_ID, "enf-1")).thenReturn(Optional.empty());
        assertThatThrownBy(() -> harness.application.lift(context(MANAGER), "lift-2", CASE_ID, "enf-1", "解除"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("DEPENDENCY_UNAVAILABLE"));
    }

    @Test
    void restoreDecisionUsesAdjustInProgressAndReturnsStructuredScopeWithoutADuplicateNotice() {
        var enforcement = mock(CasePorts.Enforcement.class);
        var decidedAt = NOW.plusSeconds(42);
        when(enforcement.plan(any(), eq(CASE_ID), any())).thenReturn(casePlan());
        when(enforcement.lockCallbacks(any(), eq(CASE_ID), any())).thenReturn(SubjectPlan.empty());
        var outcome = new CaseRecords.EnforcementOutcome("enf-1", "adjust_trade_status", "trade", TRADE_ID,
                "trade_transition", 55L, "applied",
                "status=abnormal,phase=awaiting_completion,frozen=true",
                "status=in_progress,phase=awaiting_completion,frozen=true",
                List.of(RELATED, REPORTER), NOW);
        when(enforcement.execute(any(), any(), eq(CASE_ID), anyString(), anyString(), any(), any()))
                .thenReturn(List.of(outcome));
        var harness = harness(claimedTrade(), enforcement);
        when(harness.store.decideIfClaimed(anyLong(), anyString(), anyString(), anyLong(), any()))
                .thenAnswer(invocation -> {
                    harness.facts().set(decide(harness.facts().get(), decidedAt));
                    return true;
                });
        when(harness.store.enforcements(CASE_ID)).thenReturn(List.of(new CaseRecords.Enforcement("enf-1",
                CASE_ID, "adjust_trade_status", "trade", TRADE_ID, "case:41", MANAGER, NOW,
                "trade_transition", 55L, "applied",
                "status=abnormal,phase=awaiting_completion,frozen=true",
                "status=in_progress,phase=awaiting_completion,frozen=true",
                List.of(RELATED, REPORTER), null, null, NOW, null)));
        when(harness.store.appealEligibility(anyLong(), anyLong())).thenReturn(Optional.empty());

        var result = harness.application.decide(context(MANAGER), "restore-1", CASE_ID,
                new CaseCommands.Decision("violation", "异常交易恢复", List.of(),
                        List.of(new CaseCommands.Enforcement("adjust_trade_status", "trade", TRADE_ID,
                                "in_progress"))));

        assertThat(result.status()).isEqualTo(201);
        assertThat(result.data().get("decided_at").asString()).isEqualTo(decidedAt.toString());
        var item = result.data().get("enforcements").get(0);
        assertThat(item.get("result_ref").asString()).isEqualTo("trade_transition:55");
        var scope = item.get("affected_scope");
        assertThat(scope.isArray()).isTrue();
        var scopeRefs = new java.util.ArrayList<String>();
        for (JsonNode ref : scope) {
            scopeRefs.add(ref.get("resource_type").asString() + ":" + ref.get("resource_id").asString());
        }
        assertThat(scopeRefs).containsExactly("trade:900", "account:21", "account:11");
        // publishRestore already sends one trade.restored notice per participant.
        verify(harness.notifications, never()).create(any(), anyString(), anyString(), any(), any(), any(),
                any());
    }

    @Test
    void restoreDecisionRequiresTheClaimingManagerAndTheExactCaseTrade() {
        var enforcement = mock(CasePorts.Enforcement.class);
        when(enforcement.plan(any(), eq(CASE_ID), any())).thenReturn(casePlan());
        when(enforcement.lockCallbacks(any(), eq(CASE_ID), any())).thenReturn(SubjectPlan.empty());
        var otherManager = harness(claimedTrade(OTHER_MANAGER), enforcement);

        assertThatThrownBy(() -> otherManager.application.decide(context(MANAGER), "restore-2", CASE_ID,
                new CaseCommands.Decision("violation", "异常交易恢复", List.of(),
                        List.of(new CaseCommands.Enforcement("adjust_trade_status", "trade", TRADE_ID,
                                "in_progress")))))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("NOT_CASE_MANAGER"));

        var harness = harness(claimedTrade(), enforcement);
        assertThatThrownBy(() -> harness.application.decide(context(MANAGER), "restore-3", CASE_ID,
                new CaseCommands.Decision("violation", "异常交易恢复", List.of(),
                        List.of(new CaseCommands.Enforcement("adjust_trade_status", "trade", TRADE_ID + 1,
                                "in_progress")))))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TARGET_STATE_CONFLICT"));
        verify(enforcement, never()).execute(any(), any(), anyLong(), anyString(), anyString(), any(), any());
    }

    private static CaseRecords.Enforcement recordedEnforcement() {
        return new CaseRecords.Enforcement("enf-1", CASE_ID, "restrict_account", "account", RELATED, "case:41",
                MANAGER, NOW, "account_restriction", RELATED, "applied", "active", "restricted",
                List.of(RELATED), null, null, NOW, null);
    }

    // ------------------------------------------------------------------ harness

    private static Harness harness(CaseRecords.Facts initial) {
        return harness(initial, null);
    }

    private static Harness harness(CaseRecords.Facts initial, CasePorts.Enforcement enforcement) {
        var writes = mock(WriteExecutor.class);
        var store = mock(CaseLifecycleStore.class);
        var targets = mock(CasePorts.Targets.class);
        var managers = mock(CasePorts.Managers.class);
        var accounts = mock(CasePorts.Accounts.class);
        var notifications = mock(CasePorts.Notifications.class);
        var threads = mock(CasePorts.Threads.class);
        var files = mock(CasePorts.EvidenceFiles.class);
        var transaction = mock(WriteTransaction.class);
        var facts = new AtomicReference<>(initial);
        var context = context(REPORTER);

        when(transaction.context()).thenReturn(context);
        when(transaction.audit(anyString(), any(), any(), any())).thenReturn(1L);
        org.mockito.Mockito.doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());

        when(accounts.writeRestricted(anyLong())).thenReturn(false);
        when(targets.relatedAccountIds(any())).thenReturn(Set.of(RELATED));
        when(store.find(anyLong())).thenAnswer(invocation -> Optional.of(facts.get()));
        when(store.require(anyLong())).thenAnswer(invocation -> facts.get());
        when(store.lock(any(), anyLong())).thenAnswer(invocation -> facts.get());
        when(store.requireLocked(any(), anyLong())).thenAnswer(invocation -> facts.get());
        when(store.findOpenReport(anyLong(), any())).thenReturn(Optional.empty());
        when(store.openReportIfAbsent(any(), anyLong(), anyString(), any())).thenReturn(Optional.of(CASE_ID));
        when(store.addAction(any())).thenReturn(101L);
        when(store.claim(anyLong(), anyLong(), any())).thenReturn(claimed());
        when(store.decide(anyLong(), anyString(), anyString(), anyLong(), any())).thenAnswer(invocation ->
                decide(facts.get()));
        when(store.decideIfClaimed(anyLong(), anyString(), anyString(), anyLong(), any())).thenReturn(true);
        when(store.archive(anyLong(), any())).thenAnswer(invocation -> archived());
        when(store.publish(anyLong(), anyString(), anyString(), anyLong(), any())).thenAnswer(invocation ->
                published(facts.get()));
        when(store.enforcements(anyLong())).thenReturn(List.of());
        when(store.appealEligibilities(anyLong())).thenReturn(List.of());
        when(store.latestPendingAppeal(anyLong())).thenReturn(Optional.empty());
        when(store.relatedAccountIds(anyLong())).thenReturn(List.of(RELATED));
        when(store.evidence(anyLong())).thenReturn(List.of());

        when(threads.findConversation(anyLong(), anyLong())).thenReturn(OptionalLong.of(THREAD_ID));
        when(threads.ensure(any(), anyLong(), anyLong())).thenReturn(THREAD_ID);
        when(threads.append(any(), anyLong(), anyLong(), anyString(), anyString(), anyLong(), anyString()))
                .thenReturn(new CaseRecords.ThreadMessage(THREAD_ID, 11L, 1L, NOW));
        when(threads.archive(any(), anyLong(), anyLong())).thenReturn(true);

        stubRun(writes, transaction);

        var settings = new CaseSettings();
        var application = new CaseApplication(writes, store, targets, managers, accounts, notifications, threads,
                files, enforcement, settings, JSON, Clock.fixed(NOW, ZoneOffset.UTC));
        return new Harness(application, store, targets, managers, accounts, notifications, threads, files,
                transaction, facts);
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void stubRun(WriteExecutor writes, WriteTransaction transaction) {
        when(writes.run(any(), anyString(), anyString(), any(), any())).thenAnswer(invocation -> {
            ExecutionContext execution = invocation.getArgument(0);
            when(transaction.context()).thenReturn(execution);
            WriteExecutor.UseCase<Object, Object> useCase =
                    (WriteExecutor.UseCase<Object, Object>) invocation.getArgument(4);
            Object request = invocation.getArgument(3);
            LockPlan prepared = useCase.prepare(execution, request);
            useCase.qualify(execution, request, prepared);
            WriteResult.Response<?> response = useCase.write(transaction, request, null, prepared);
            return new WriteResult<>(UUID.randomUUID(), response.status(), (JsonNode) response.data(),
                    response.resource(), false);
        });
    }

    private static CaseRecords.Facts pending() {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "account", RELATED, null, null,
                REPORTER, "虚假信息", null, null, CaseVocabulary.PENDING, null, null, null, null, null,
                null, null, null, NOW, NOW);
    }

    private static CaseRecords.Facts messageCase() {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "message", 55L, "chat", 77L,
                REPORTER, "虚假信息", MANAGER, NOW, CaseVocabulary.CLAIMED, null, null, null, null, null,
                null, null, null, NOW, NOW);
    }

    private static CaseRecords.Facts claimed() {
        return claimedBy(MANAGER);
    }

    private static CaseRecords.Facts claimedBy(long manager) {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "account", RELATED, null, null,
                REPORTER, "虚假信息", manager, NOW, CaseVocabulary.CLAIMED, null, null, null, null, null,
                null, null, null, NOW, NOW);
    }

    private static CaseRecords.Facts claimedTrade() {
        return claimedTrade(MANAGER);
    }

    private static CaseRecords.Facts claimedTrade(long manager) {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.EXCEPTION, "trade", TRADE_ID, null, null,
                REPORTER, "单方确认超时", manager, NOW, CaseVocabulary.CLAIMED, null, null, null, null, null,
                null, null, null, NOW, NOW);
    }

    private static LockPlan casePlan() {
        return new LockPlan(Map.of(MANAGER, LockPlan.AccountMode.SHARED),
                Set.of(new LockPlan.Key(LockPlan.Domain.CASE, List.of(CASE_ID))));
    }

    private static CaseRecords.Facts decided() {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "account", RELATED, null, null,
                REPORTER, "虚假信息", MANAGER, NOW, CaseVocabulary.DECIDED, CaseVocabulary.VIOLATION,
                "认定违规", MANAGER, NOW, null, null, null, null, NOW, NOW);
    }

    private static CaseRecords.Facts archived() {
        return new CaseRecords.Facts(CASE_ID, CaseVocabulary.REPORT, "account", RELATED, null, null,
                REPORTER, "虚假信息", MANAGER, NOW, CaseVocabulary.DECIDED, CaseVocabulary.VIOLATION,
                "认定违规", MANAGER, NOW, NOW, null, null, null, NOW, NOW);
    }

    private static CaseRecords.Facts decide(CaseRecords.Facts facts) {
        return decide(facts, NOW);
    }

    private static CaseRecords.Facts decide(CaseRecords.Facts facts, Instant decidedAt) {
        return new CaseRecords.Facts(facts.caseId(), facts.caseType(), facts.targetType(), facts.targetId(),
                facts.conversationKind(), facts.conversationId(), facts.reporterAccountId(),
                facts.reportedReason(), facts.claimedManagerId(), facts.claimedAt(), CaseVocabulary.DECIDED,
                CaseVocabulary.VIOLATION, "认定违规", facts.claimedManagerId(), decidedAt, null, null, null,
                null, facts.createdAt(), NOW);
    }

    private static CaseRecords.Facts published(CaseRecords.Facts facts) {
        return new CaseRecords.Facts(facts.caseId(), facts.caseType(), facts.targetType(), facts.targetId(),
                facts.conversationKind(), facts.conversationId(), facts.reporterAccountId(),
                facts.reportedReason(), facts.claimedManagerId(), facts.claimedAt(), facts.caseStatus(),
                facts.decisionKind(), facts.reasonText(), facts.decidedBy(), facts.decidedAt(),
                facts.archivedAt(), "认定违规", "依据证据", NOW, facts.createdAt(), NOW);
    }

    private static ExecutionContext context(long actor) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(actor), UUID.randomUUID(), null, 1L, "test");
    }

    private record Harness(CaseApplication application, CaseLifecycleStore store, CasePorts.Targets targets,
                           CasePorts.Managers managers, CasePorts.Accounts accounts,
                           CasePorts.Notifications notifications, CasePorts.Threads threads,
                           CasePorts.EvidenceFiles files, WriteTransaction transaction,
                           AtomicReference<CaseRecords.Facts> facts) {
    }
}
