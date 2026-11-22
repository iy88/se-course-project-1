package io.github.iy88.project1.notification.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

class NotificationIntentTests {
    private static final Instant OCCURRED = Instant.parse("2026-11-20T08:55:00Z");

    @Test
    void foldsTheRegistryLabelOntoTheSharedEventIntentName() {
        var intent = new NotificationIntent(Set.of(1L), null, "product_audit.rejected",
                new ResourceRef("product_audit", 5L), "key", "template", "1", Map.of(), OCCURRED);

        assertThat(intent.eventIntentType()).isEqualTo("product_audit_rejected");
    }

    @Test
    void sortsAndDeduplicatesRecipients() {
        Set<Long> recipients = new java.util.HashSet<>(java.util.List.of(9L, 3L, 9L));
        var intent = new NotificationIntent(recipients, null, "case.inquiry_created",
                new ResourceRef("case", 5L), "key", "template", "1", Map.of(), OCCURRED);

        assertThat(intent.sortedRecipients()).containsExactly(3L, 9L);
    }

    @Test
    void rejectsAnEmptyRecipientSet() {
        assertThatThrownBy(() -> new NotificationIntent(Set.of(), null, "case.inquiry_created",
                new ResourceRef("case", 5L), "key", "template", "1", Map.of(), OCCURRED))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsABlankIntentKey() {
        assertThatThrownBy(() -> new NotificationIntent(Set.of(1L), null, "case.inquiry_created",
                new ResourceRef("case", 5L), " ", "template", "1", Map.of(), OCCURRED))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void reviewAdapterAddsTheSellerOnlyAndKeepsTheAuditInTheIntentKey() {
        var store = new InMemoryNotificationStore();
        var application = new NotificationApplication(store, Clock.fixed(OCCURRED, ZoneOffset.UTC));
        var adapter = new ReviewNotificationAdapter(application);
        WriteTransaction transaction = mock(WriteTransaction.class);

        adapter.reviewDecided(transaction, 7L, 1001L, 42L, "rejected", "封面图片含盗版影印页面", OCCURRED);

        var stored = store.find(7L, ReviewNotificationAdapter.intentKey(1001L)).orElseThrow();
        assertThat(stored.eventType()).isEqualTo(ReviewNotificationAdapter.eventType("rejected"));
        assertThat(stored.source()).isEqualTo(new ResourceRef("product_audit", 1001L));
        assertThat(stored.displayParams()).containsEntry("reason", "封面图片含盗版影印页面");
        assertThat(stored.displayParams()).containsEntry("product_id", "42");
        verify(transaction).addEventIntent(eq(Set.of(7L)), eq("product_audit_rejected"), eq(1),
                eq(new ResourceRef("product_audit", 1001L)), eq(ReviewNotificationAdapter.intentKey(1001L)),
                eq(null), eq(null));
    }

    @Test
    void reviewAdapterOmitsAnEmptyReason() {
        var store = new InMemoryNotificationStore();
        var application = new NotificationApplication(store, Clock.fixed(OCCURRED, ZoneOffset.UTC));
        var adapter = new ReviewNotificationAdapter(application);

        adapter.reviewDecided(mock(WriteTransaction.class), 7L, 1002L, 43L, "passed", null, OCCURRED);

        var stored = store.find(7L, ReviewNotificationAdapter.intentKey(1002L)).orElseThrow();
        assertThat(stored.eventType()).isEqualTo("product_audit.passed");
        assertThat(stored.displayParams()).doesNotContainKey("reason");
    }

    @Test
    void enforcementAdapterCarriesTheCaseSourceAndAffectedAccounts() {
        var store = new InMemoryNotificationStore();
        var application = new NotificationApplication(store, Clock.fixed(OCCURRED, ZoneOffset.UTC));
        var adapter = new EnforcementNotificationAdapter(application);

        adapter.create(mock(WriteTransaction.class), "case.trade_frozen", "case.enforcement:22", 
                new ResourceRef("case", 22L), Set.of(5L, 6L), "交易存在异常，暂停确认计时", OCCURRED);

        var first = store.find(5L, "case.enforcement:22").orElseThrow();
        assertThat(first.eventType()).isEqualTo("case.trade_frozen");
        assertThat(first.source()).isEqualTo(new ResourceRef("case", 22L));
        assertThat(first.displayParams()).containsEntry("reason", "交易存在异常，暂停确认计时");
        assertThat(store.size()).isEqualTo(2);
    }
}
