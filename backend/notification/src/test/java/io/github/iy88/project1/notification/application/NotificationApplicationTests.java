package io.github.iy88.project1.notification.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class NotificationApplicationTests {
    private static final Instant NOW = Instant.parse("2026-11-20T09:00:00Z");
    private static final Instant OCCURRED = Instant.parse("2026-11-20T08:55:00Z");
    private static final ResourceRef PRODUCT_AUDIT = new ResourceRef("product_audit", 1001L);

    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private InMemoryNotificationStore store;
    private NotificationApplication application;
    private WriteTransaction transaction;

    @BeforeEach
    void setUp() {
        store = new InMemoryNotificationStore();
        application = new NotificationApplication(store, clock);
        transaction = mock(WriteTransaction.class);
        when(transaction.addEventIntent(any(), any(), anyInt(), any(), any(), any(), any()))
                .thenReturn(new EventIntent.Batch(List.of()));
    }

    @Test
    @SuppressWarnings("unchecked")
    void persistsOneNotificationPerRecipientAndRegistersOneCreatedEventEach() {
        var intent = intent(Set.of(7L, 3L), "product_audit.decision:1001");

        var batch = application.createNotifications(transaction, intent);

        assertThat(batch.items()).hasSize(2);
        assertThat(batch.items()).extracting(NotificationItem::recipientAccountId).containsExactly(3L, 7L);
        assertThat(batch.items()).allSatisfy(item -> assertThat(item.readAt()).isNull());
        assertThat(store.size()).isEqualTo(2);

        // The business label stays in the row; delivery is always notification_created
        // and carries the created notification id for that recipient.
        var recipients = ArgumentCaptor.forClass(Set.class);
        var eventTypes = ArgumentCaptor.forClass(String.class);
        var payloads = ArgumentCaptor.forClass(ResourceRef.class);
        verify(transaction, times(2)).addEventIntent(recipients.capture(), eventTypes.capture(), eq(1),
                eq(PRODUCT_AUDIT), eq("product_audit.decision:1001"), payloads.capture(), any());
        assertThat(eventTypes.getAllValues()).containsOnly(NotificationApplication.CREATED_EVENT_TYPE);
        assertThat(recipients.getAllValues()).containsExactly(Set.of(3L), Set.of(7L));
        assertThat(payloads.getAllValues()).containsExactly(
                new ResourceRef("notification", batch.items().get(0).notificationId()),
                new ResourceRef("notification", batch.items().get(1).notificationId()));
    }

    @Test
    void replayingTheSameIntentReturnsTheStoredNotificationAndRegistersNoSecondEvent() {
        var intent = intent(Set.of(7L), "product_audit.decision:1001");
        var first = application.createNotifications(transaction, intent);
        var second = application.createNotifications(transaction, intent);

        assertThat(second.items()).isEqualTo(first.items());
        assertThat(store.size()).isEqualTo(1);
        verify(transaction, times(1)).addEventIntent(any(), any(), anyInt(), any(), any(), any(), any());
    }

    @Test
    void rejectsTheSameKeyWithADifferentEventType() {
        application.createNotifications(transaction, intent(Set.of(7L), "product_audit.decision:1001"));
        var conflicting = new NotificationIntent(Set.of(7L), null, "product_audit.rejected", PRODUCT_AUDIT,
                "product_audit.decision:1001", "product_audit.decision", "1",
                Map.of("reason", "含盗版影印页面"), OCCURRED);

        assertThatThrownBy(() -> application.createNotifications(transaction, conflicting))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> {
                    var failure = (BusinessError) error;
                    assertThat(failure.code()).isEqualTo("NOTIFICATION_INTENT_CONFLICT");
                    assertThat(failure.status()).isEqualTo(409);
                });
    }

    @Test
    void rejectsTheSameKeyWithADifferentTemplateParameter() {
        application.createNotifications(transaction, intent(Set.of(7L), "product_audit.decision:1001"));
        // Same event type, source and template; only the reason differs.
        var conflicting = new NotificationIntent(Set.of(7L), null, "product_audit.passed", PRODUCT_AUDIT,
                "product_audit.decision:1001", "product_audit.decision", "1",
                Map.of("product_id", "42", "decision", "passed", "reason", "不同理由"), OCCURRED);

        assertThatThrownBy(() -> application.createNotifications(transaction, conflicting))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code())
                        .isEqualTo("NOTIFICATION_INTENT_CONFLICT"));
        assertThat(store.size()).isEqualTo(1);
    }

    @Test
    @SuppressWarnings("unchecked")
    void registersDeliveryIntentsOnlyForNewlyCreatedRecipients() {
        application.createNotifications(transaction, intent(Set.of(3L), "product_audit.decision:1001"));
        application.createNotifications(transaction, intent(Set.of(3L, 7L), "product_audit.decision:1001"));

        // The first call registers one recipient, the second only the new one.
        var recipients = ArgumentCaptor.forClass(Set.class);
        verify(transaction, times(2)).addEventIntent(recipients.capture(), eq(NotificationApplication.CREATED_EVENT_TYPE),
                eq(1), eq(PRODUCT_AUDIT), eq("product_audit.decision:1001"), any(), any());
        assertThat(recipients.getAllValues()).containsExactly(Set.of(3L), Set.of(7L));
        assertThat(store.size()).isEqualTo(2);
    }

    @Test
    void recordsTheFirstReadAndRegistersOneReadEvent() {
        var created = application.createNotifications(transaction, intent(Set.of(7L), "product_audit.decision:1001"));
        long notificationId = created.items().getFirst().notificationId();

        var read = application.markRead(transaction, 7L, notificationId);

        assertThat(read.readAt()).isEqualTo(NOW);
        verify(transaction).addEventIntent(eq(Set.of(7L)), eq("notification_read"), eq(1), eq(PRODUCT_AUDIT),
                eq("notification_read:" + notificationId), eq(new ResourceRef("notification", notificationId)),
                any());
    }

    @Test
    void keepsTheStoredReadInstantOnASecondRead() {
        var created = application.createNotifications(transaction, intent(Set.of(7L), "product_audit.decision:1001"));
        long notificationId = created.items().getFirst().notificationId();

        // First read happens at NOW; the same value is returned later.
        application.markRead(transaction, 7L, notificationId);
        var later = new NotificationApplication(store, Clock.fixed(NOW.plusSeconds(600), ZoneOffset.UTC));
        var second = later.markRead(transaction, 7L, notificationId);

        assertThat(second.readAt()).isEqualTo(NOW);
        verify(transaction, times(1)).addEventIntent(eq(Set.of(7L)), eq("notification_read"), eq(1), any(),
                any(), any(), any());
    }

    @Test
    void refusesToReadAnotherAccountsNotification() {
        var created = application.createNotifications(transaction, intent(Set.of(7L), "product_audit.decision:1001"));
        long notificationId = created.items().getFirst().notificationId();
        WriteTransaction readerTransaction = mock(WriteTransaction.class);

        assertThatThrownBy(() -> application.markRead(readerTransaction, 9L, notificationId))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
        verify(readerTransaction, never()).addEventIntent(any(), any(), anyInt(), any(), any(), any(), any());
    }

    private static NotificationIntent intent(Set<Long> recipients, String intentKey) {
        return new NotificationIntent(recipients, null, "product_audit.passed", PRODUCT_AUDIT, intentKey,
                "product_audit.decision", "1", Map.of("product_id", "42", "decision", "passed"), OCCURRED);
    }
}
