package io.github.iy88.project1.api.product;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.UserEvents;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationBatch;
import io.github.iy88.project1.notification.application.NotificationEventSink;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class TradeProductEditNotificationConfigurationTests {
    private static final long SELLER = 7L;
    private static final long PRODUCT = 10L;
    private static final long EDIT = 99L;
    private static final Instant NOW = Instant.parse("2026-11-23T04:00:00Z");

    private final NotificationApplication notifications = mock(NotificationApplication.class);
    private final UserEvents events = mock(UserEvents.class);
    private final TradeOwnedReadModel trades = mock(TradeOwnedReadModel.class);
    private final TradeProductEditNotificationConfiguration configuration =
            new TradeProductEditNotificationConfiguration();

    @Test
    void oneStableIntentPerActiveTradeAndRecipientWithRealTransportEvents() {
        when(trades.productNoticeTargets(PRODUCT)).thenReturn(List.of(
                new TradeOwnedReadModel.ProductNoticeTarget(11, 8, "旧书"),
                new TradeOwnedReadModel.ProductNoticeTarget(12, 9, "旧书")));
        doAnswer(call -> {
            NotificationEventSink sink = call.getArgument(0);
            NotificationIntent intent = call.getArgument(1);
            for (long recipient : intent.sortedRecipients()) {
                sink.register(java.util.Set.of(recipient), NotificationApplication.CREATED_EVENT_TYPE,
                        NotificationApplication.SCHEMA_VERSION, intent.source(), intent.intentKey(),
                        new ResourceRef("notification", 100 + recipient), null);
            }
            return new NotificationBatch(List.of());
        }).when(notifications).createNotifications(any(NotificationEventSink.class), any(NotificationIntent.class));

        var context = context();
        configuration.productEditNotices(notifications, events, trades).productEdited(context, SELLER,
                PRODUCT, EDIT, "旧书", true, NOW);

        ArgumentCaptor<NotificationIntent> intents = ArgumentCaptor.forClass(NotificationIntent.class);
        verify(notifications, times(2)).createNotifications(any(NotificationEventSink.class), intents.capture());
        assertThat(intents.getAllValues()).extracting(element -> element.intentKey())
                .containsExactly("trade.product_updated:99:11", "trade.product_updated:99:12");
        assertThat(intents.getAllValues()).extracting(entry -> entry.eventType())
                .containsOnly("trade.product_updated");
        assertThat(intents.getAllValues()).extracting(value -> value.source())
                .containsExactly(new ResourceRef("trade_product_edit", 11),
                        new ResourceRef("trade_product_edit", 12));
        verify(events).persist(eq(context), anyList());
    }

    @Test
    void nonPublicProductDoesNotNotifyAnyone() {
        configuration.productEditNotices(notifications, events, trades).productEdited(context(), SELLER,
                PRODUCT, EDIT, "旧书", false, NOW);

        verifyNoInteractions(notifications, events, trades);
    }

    @Test
    void sourceProjectionPointsBackToTheTradeForAParticipant() {
        when(trades.productNoticeContext(11, 8))
                .thenReturn(Optional.of(new TradeOwnedReadModel.ProductNoticeContext("旧书", "想要")));
        NotificationSourcePort port = configuration.tradeProductEditNotificationSource(trades);

        var view = port.project(contextFor(8), facts()).orElseThrow();

        assertThat(view.summary()).isEqualTo(TradeProductEditNotificationConfiguration.SUMMARY);
        assertThat(view.source()).isEqualTo(new ResourceRef("trade", 11));
        assertThat(view.subject()).isEqualTo("旧书");
    }

    @Test
    void sourceProjectionHidesTheTradeWhenTheReaderIsNotAParticipant() {
        when(trades.productNoticeContext(11, 8)).thenReturn(Optional.empty());

        assertThat(configuration.tradeProductEditNotificationSource(trades)
                .project(contextFor(8), facts())).isEmpty();
        verify(notifications, never()).createNotifications(any(NotificationEventSink.class),
                any(NotificationIntent.class));
        verifyNoInteractions(events);
    }

    private static NotificationSourcePort.NotificationFacts facts() {
        return new NotificationSourcePort.NotificationFacts(1, 8, "trade.product_updated",
                new ResourceRef("trade_product_edit", 11), "trade.product_updated", "1", java.util.Map.of(),
                NOW, null, "trade.product_updated:21:11", true);
    }

    private static ExecutionContext context() {
        return contextFor(SELLER);
    }

    private static ExecutionContext contextFor(long account) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(account), UUID.randomUUID(), null, 1L, "cfg");
    }
}
