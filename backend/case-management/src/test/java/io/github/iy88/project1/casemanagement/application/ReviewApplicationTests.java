package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReviewApplicationTests {
    private static final LockPlan.Key PRODUCT = new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(9L));
    private static final LockPlan.Key CASE = new LockPlan.Key(LockPlan.Domain.CASE, List.of(3L));

    @Test
    void claimsTheProductReviewBeforeTheCaseOwnership() {
        var writes = mock(WriteExecutor.class);
        var products = mock(ProductReviewPort.class);
        var cases = mock(CaseReviewPort.class);
        var transaction = mock(WriteTransaction.class);
        var command = new ReviewCommand(3, 9, ReviewAction.CLAIM, null, List.of(), null, null,
                Instant.parse("2026-01-01T00:00:00Z"));
        var productPlan = SubjectPlan.resource(PRODUCT, ignored -> {});
        var casePlan = SubjectPlan.resource(CASE, ignored -> {});
        when(products.prepare(command)).thenReturn(productPlan);
        when(cases.prepare(command)).thenReturn(casePlan);
        when(products.claim(transaction, command)).thenReturn(new ReviewSubject(
                new ResourceRef("product_audit", 9), "PENDING", "CLAIMED", false));
        var prepared = productPlan.merge(casePlan).lockPlan();
        var application = new ReviewApplication(writes, products, cases, JsonMapper.builder().build());

        WriteResult.Response<?> response = application.write(transaction, command, true, prepared);

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.data()).isInstanceOf(ReviewOutcome.class);
        var productOrder = inOrder(transaction);
        productOrder.verify(transaction).lock(org.mockito.ArgumentMatchers.eq(PRODUCT), any());
        productOrder.verify(transaction).lock(org.mockito.ArgumentMatchers.eq(CASE), any());
        var subjectOrder = inOrder(products, cases);
        subjectOrder.verify(products).claim(transaction, command);
        subjectOrder.verify(cases).claim(transaction, command);
        verify(cases, never()).recordDecision(any(), any(), any());
    }

    @Test
    void recordsAReviewDecisionAfterTheProductCapabilityReturnsItsResult() {
        var writes = mock(WriteExecutor.class);
        var products = mock(ProductReviewPort.class);
        var cases = mock(CaseReviewPort.class);
        var transaction = mock(WriteTransaction.class);
        var command = new ReviewCommand(3, 9, ReviewAction.REJECT, "not allowed", List.of(4L), null, null,
                Instant.parse("2026-01-01T00:00:00Z"));
        var productPlan = SubjectPlan.resource(PRODUCT, ignored -> {});
        var casePlan = SubjectPlan.resource(CASE, ignored -> {});
        when(products.prepare(command)).thenReturn(productPlan);
        when(cases.prepare(command)).thenReturn(casePlan);
        var subject = new ReviewSubject(new ResourceRef("product_audit", 9), "PENDING", "REJECTED", false);
        when(products.decide(transaction, command)).thenReturn(subject);
        var prepared = new LockPlan(Map.of(), Set.of(PRODUCT, CASE));
        var application = new ReviewApplication(writes, products, cases, JsonMapper.builder().build());

        application.write(transaction, command, true, prepared);

        var subjectOrder = inOrder(products, cases);
        subjectOrder.verify(products).decide(transaction, command);
        subjectOrder.verify(cases).recordDecision(transaction, command, subject);
    }
}
