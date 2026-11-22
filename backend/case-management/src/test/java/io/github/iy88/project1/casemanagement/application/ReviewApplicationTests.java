package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class ReviewApplicationTests {
    private static final long CASE_ID = 3;
    private static final long AUDIT_ID = 9;
    private static final long PRODUCT_ID = 11;
    private static final long SELLER_ID = 21;
    private static final long MANAGER_ID = 7;
    private static final Instant NOW = Instant.parse("2026-01-01T00:00:00Z");
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final LockPlan.Key PRODUCT = new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(PRODUCT_ID));
    private static final LockPlan.Key AUDIT = new LockPlan.Key(LockPlan.Domain.PRODUCT_AUDIT, List.of(AUDIT_ID));
    private static final LockPlan.Key CASE = new LockPlan.Key(LockPlan.Domain.CASE, List.of(CASE_ID));

    @Test
    void claimLocksTheProductBeforeTheCaseAndWritesOneOwnershipFact() {
        var harness = harness();
        when(harness.products.prepareClaim(CASE_ID))
                .thenReturn(SubjectPlan.resource(PRODUCT, ignored -> {}));
        when(harness.cases.plan(CASE_ID)).thenReturn(SubjectPlan.resource(CASE, ignored -> {}));
        when(harness.products.requirePendingForClaim(CASE_ID)).thenReturn(AUDIT_ID);
        when(harness.cases.read(CASE_ID)).thenReturn(unclaimed());
        stubRun(harness);

        var result = harness.application.claim(harness.context, "claim-key-0000001", CASE_ID);

        assertThat(result.data().path("case_id").stringValue()).isEqualTo("3");
        assertThat(result.data().path("case_status").stringValue()).isEqualTo("claimed");
        assertThat(result.data().path("already_claimed").booleanValue()).isFalse();
        verify(harness.cases).claim(CASE_ID, MANAGER_ID, NOW);
        verify(harness.transaction).audit(eq("case.review.claim"),
                eq(new ResourceRef("product_audit", AUDIT_ID)), eq(new ResourceRef("case", CASE_ID)), any());
        var lockOrder = inOrder(harness.transaction);
        lockOrder.verify(harness.transaction).lock(eq(PRODUCT), any());
        lockOrder.verify(harness.transaction).lock(eq(CASE), any());
        verify(harness.products, never()).decide(any(), any());
    }

    @Test
    void repeatClaimByTheSameManagerReturnsTheOriginalTimeWithoutANewFact() {
        var harness = harness();
        when(harness.products.prepareClaim(CASE_ID))
                .thenReturn(SubjectPlan.resource(PRODUCT, ignored -> {}));
        when(harness.cases.plan(CASE_ID)).thenReturn(SubjectPlan.resource(CASE, ignored -> {}));
        when(harness.products.requirePendingForClaim(CASE_ID)).thenReturn(AUDIT_ID);
        var original = Instant.parse("2025-12-31T00:00:00Z");
        when(harness.cases.read(CASE_ID))
                .thenReturn(new CaseClaim(CASE_ID, "product_review", NOW, MANAGER_ID, original));
        stubRun(harness);

        var result = harness.application.claim(harness.context, "claim-key-0000002", CASE_ID);

        assertThat(result.data().path("already_claimed").booleanValue()).isTrue();
        assertThat(result.data().path("claimed_at").stringValue()).isEqualTo(original.toString());
        verify(harness.cases, never()).claim(anyLong(), anyLong(), any());
        verify(harness.transaction, never()).audit(anyString(), any(), any(), any());
    }

    @Test
    void anotherManagerCannotTakeOverAnExistingClaim() {
        var harness = harness();
        when(harness.products.prepareClaim(CASE_ID))
                .thenReturn(SubjectPlan.resource(PRODUCT, ignored -> {}));
        when(harness.cases.plan(CASE_ID)).thenReturn(SubjectPlan.resource(CASE, ignored -> {}));
        when(harness.products.requirePendingForClaim(CASE_ID)).thenReturn(AUDIT_ID);
        when(harness.cases.read(CASE_ID))
                .thenReturn(new CaseClaim(CASE_ID, "product_review", NOW, MANAGER_ID + 1, NOW));
        stubRun(harness);

        assertThatThrownBy(() -> harness.application.claim(harness.context, "claim-key-0000003", CASE_ID))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("CASE_ALREADY_CLAIMED");
                    assertThat(error.status()).isEqualTo(409);
                });
        verify(harness.cases, never()).claim(anyLong(), anyLong(), any());
    }

    @Test
    void decisionWritesTheProductResultThenTheCaseActionNotificationAndAudit() {
        var harness = harness();
        when(harness.products.prepareDecision(AUDIT_ID))
                .thenReturn(new ReviewPlan(SubjectPlan.resource(AUDIT, ignored -> {}), CASE_ID));
        when(harness.cases.plan(CASE_ID)).thenReturn(SubjectPlan.resource(CASE, ignored -> {}));
        when(harness.cases.read(CASE_ID)).thenReturn(claimed());
        var decided = new DecisionResult(AUDIT_ID, CASE_ID, PRODUCT_ID, SELLER_ID, "rejected", "review_rejected",
                2, 2, null, NOW, "not allowed");
        when(harness.products.decide(eq(harness.transaction), any())).thenReturn(decided);
        stubRun(harness);

        var result = harness.application.decide(harness.context, "decide-key-0000001",
                new ReviewDecisionInput(AUDIT_ID, ReviewAction.REJECT, "not allowed", List.of(4L),
                        null, null));

        assertThat(result.data().path("status").stringValue()).isEqualTo("rejected");
        assertThat(result.data().path("case_status").stringValue()).isEqualTo("decided");
        assertThat(result.data().path("product").path("lifecycle_state").stringValue()).isEqualTo("review_rejected");
        var order = inOrder(harness.products, harness.cases, harness.notifications, harness.transaction);
        order.verify(harness.products).decide(eq(harness.transaction), any());
        order.verify(harness.cases).recordDecision(CASE_ID, MANAGER_ID, NOW);
        order.verify(harness.transaction).audit(eq("case.review.reject"),
                eq(new ResourceRef("product_audit", AUDIT_ID)), eq(new ResourceRef("case", CASE_ID)), any());
        order.verify(harness.notifications).reviewDecided(harness.transaction, SELLER_ID, AUDIT_ID, PRODUCT_ID,
                "rejected", "not allowed", NOW);
    }

    @Test
    void decisionRejectsANonClaimantBeforeCallingTheProduct() {
        var harness = harness();
        when(harness.products.prepareDecision(AUDIT_ID))
                .thenReturn(new ReviewPlan(SubjectPlan.resource(AUDIT, ignored -> {}), CASE_ID));
        when(harness.cases.plan(CASE_ID)).thenReturn(SubjectPlan.resource(CASE, ignored -> {}));
        when(harness.cases.read(CASE_ID))
                .thenReturn(new CaseClaim(CASE_ID, "product_review", NOW, MANAGER_ID + 1, NOW));
        stubRun(harness);

        assertThatThrownBy(() -> harness.application.decide(harness.context, "decide-key-0000002",
                new ReviewDecisionInput(AUDIT_ID, ReviewAction.APPROVE, null, List.of(), null, null)))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE");
                    assertThat(error.status()).isEqualTo(404);
                });
        verify(harness.products, never()).decide(any(), any());
        verify(harness.notifications, never()).reviewDecided(any(), anyLong(), anyLong(), anyLong(),
                anyString(), any(), any());
    }

    @Test
    void missingNotificationPortFailsBeforeReservingTheIdempotencyKey() {
        var writes = mock(WriteExecutor.class);
        var cases = mock(ReviewCaseStore.class);
        var products = mock(ProductReviewPort.class);
        var managers = mock(ReviewManagerAccess.class);
        var application = new ReviewApplication(writes, cases, JSON, products, managers, null,
                Clock.fixed(NOW, ZoneOffset.UTC));
        var context = context();

        assertThatThrownBy(() -> application.decide(context, "decide-key-0000003",
                new ReviewDecisionInput(AUDIT_ID, ReviewAction.APPROVE, null, List.of(), null, null)))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("DEPENDENCY_UNAVAILABLE");
                    assertThat(error.status()).isEqualTo(503);
                });
        verifyNoInteractions(writes, products);
    }

    @Test
    void detailProjectsOnlyTheClaimantAndTheNeededReviewFacts() {
        var harness = harness();
        when(harness.products.caseIdForAudit(AUDIT_ID)).thenReturn(CASE_ID);
        when(harness.cases.read(CASE_ID)).thenReturn(claimed());
        when(harness.products.detail(harness.context, AUDIT_ID)).thenReturn(detail());

        var body = harness.application.detail(harness.context, AUDIT_ID);

        assertThat(body.path("seller").path("display_name").stringValue()).isEqualTo("Seller");
        assertThat(body.path("claim").path("manager_id").stringValue()).isEqualTo("7");
        assertThat(body.path("current_content").path("categories").get(0).path("id").stringValue()).isEqualTo("5");
        assertThat(body.path("banned_scope").get(0).path("group").stringValue()).isEqualTo("medicine_device");
        assertThat(body.path("review_result").isNull()).isTrue();
    }

    @Test
    void detailHidesAnUnclaimedReview() {
        var harness = harness();
        when(harness.cases.read(CASE_ID)).thenReturn(unclaimed());
        when(harness.products.caseIdForAudit(AUDIT_ID)).thenReturn(CASE_ID);

        assertThatThrownBy(() -> harness.application.detail(harness.context, AUDIT_ID))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
    }

    @Test
    void decisionReplansWhenLockingRevealsAnotherCategory() {
        var harness = harness();
        var category = new LockPlan.Key(LockPlan.Domain.CATEGORY, List.of(40L));
        var original = SubjectPlan.resource(AUDIT, ignored -> {});
        var expanded = original.merge(SubjectPlan.resource(category, ignored -> {}));
        when(harness.products.prepareDecision(AUDIT_ID))
                .thenReturn(new ReviewPlan(original, CASE_ID), new ReviewPlan(original, CASE_ID),
                        new ReviewPlan(expanded, CASE_ID));
        when(harness.cases.plan(CASE_ID)).thenReturn(SubjectPlan.resource(CASE, ignored -> {}));
        stubRun(harness);

        assertThatThrownBy(() -> harness.application.decide(harness.context, "decide-replan",
                new ReviewDecisionInput(AUDIT_ID, ReviewAction.APPROVE, null, List.of(), null, null)))
                .isInstanceOfSatisfying(LockPlan.Changed.class,
                        changed -> assertThat(changed.additional().resources()).containsExactly(category));
        verify(harness.products, never()).decide(any(), any());
    }

    @Test
    void todoResponseFillsAllLegalKindsAndKeepsTheAuditIdInTheSummary() {
        var harness = harness();
        when(harness.products.todos(any())).thenReturn(new TodoPage(
                List.of(new TodoItem(CASE_ID, TodoKinds.PRODUCT_REVIEW, NOW, NOW, AUDIT_ID, PRODUCT_ID)),
                1, Map.of(TodoKinds.PRODUCT_REVIEW, 1L), NOW));

        var body = harness.application.todos(harness.context, "unclaimed", "product_review", 1, 20);

        assertThat(body.path("items").get(0).path("summary").path("audit_id").stringValue()).isEqualTo("9");
        assertThat(body.path("counts_by_kind").path("product_review").asLong()).isEqualTo(1);
        assertThat(body.path("counts_by_kind").path("report").asLong()).isZero();
        assertThat(body.path("counts_by_kind").path("dispute").asLong()).isZero();
        assertThat(body.path("counts_by_kind").path("exception").asLong()).isZero();
    }

    @Test
    void rejectsAnUnknownTodoKindAndInvalidPagination() {
        var harness = harness();
        assertThatThrownBy(() -> harness.application.todos(harness.context, "unclaimed", "other", 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        verifyNoInteractions(harness.products);
    }

    @Test
    void decisionValidationRequiresAReasonForRejection() {
        assertThatThrownBy(() -> new ReviewDecisionInput(AUDIT_ID, ReviewAction.REJECT, " ", List.of(), null, null))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        assertThatThrownBy(() -> new ReviewDecisionInput(AUDIT_ID, ReviewAction.APPROVE, null, List.of(),
                ReviewAction.REJECT, " "))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }

    private static Harness harness() {
        var writes = mock(WriteExecutor.class);
        var cases = mock(ReviewCaseStore.class);
        var products = mock(ProductReviewPort.class);
        var managers = mock(ReviewManagerAccess.class);
        var notifications = mock(ReviewNotifications.class);
        var transaction = mock(WriteTransaction.class);
        var context = context();
        when(transaction.context()).thenReturn(context);
        doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(1)).run();
            return null;
        }).when(transaction).lock(any(), any());
        when(transaction.audit(anyString(), any(), any(), any())).thenReturn(1L);
        var application = new ReviewApplication(writes, cases, JSON, products, managers, notifications,
                Clock.fixed(NOW, ZoneOffset.UTC));
        return new Harness(writes, cases, products, managers, notifications, transaction, context, application);
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void stubRun(Harness harness) {
        when(harness.writes.run(any(), anyString(), anyString(), any(), any())).thenAnswer(invocation -> {
            WriteExecutor.UseCase<Object, Object> useCase =
                    (WriteExecutor.UseCase<Object, Object>) invocation.getArgument(4);
            Object request = invocation.getArgument(3);
            LockPlan prepared = useCase.prepare(harness.context, request);
            useCase.qualify(harness.context, request, prepared);
            WriteResult.Response<?> response = useCase.write(harness.transaction, request, true, prepared);
            return new WriteResult<>(UUID.randomUUID(), response.status(), (JsonNode) response.data(),
                    response.resource(), false);
        });
    }

    private static ExecutionContext context() {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(MANAGER_ID), UUID.randomUUID(), null, 1L, "test");
    }


    private static CaseClaim unclaimed() {
        return new CaseClaim(CASE_ID, "product_review", NOW, null, null);
    }

    private static CaseClaim claimed() {
        return new CaseClaim(CASE_ID, "product_review", NOW, MANAGER_ID, NOW);
    }

    private static ProductReviewDetail detail() {
        return new ProductReviewDetail(AUDIT_ID, PRODUCT_ID, CASE_ID, "pending", NOW,
                new ProductReviewDetail.Seller(SELLER_ID, "Seller"),
                new ProductReviewDetail.CurrentContent("Title", "Description", List.of(), 1000, List.of(new ProductReviewDetail.Category(5L, "Category")), 2),
                null,
                List.of(new ProductReviewDetail.BannedItem(4L, "medicine_device", "content")),
                null);
    }

    private record Harness(WriteExecutor writes, ReviewCaseStore cases, ProductReviewPort products,
                           ReviewManagerAccess managers, ReviewNotifications notifications,
                           WriteTransaction transaction, ExecutionContext context, ReviewApplication application) {
    }
}
