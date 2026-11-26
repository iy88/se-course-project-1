package io.github.iy88.project1.notification.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class NotificationQueriesTests {
    private static final Instant NOW = Instant.parse("2026-11-20T09:00:00Z");
    private static final Instant OCCURRED = Instant.parse("2026-11-20T08:55:00Z");
    private static final ResourceRef PRODUCT = new ResourceRef("product", 42L);
    private static final long READER = 7L;

    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private InMemoryNotificationStore store;
    private NotificationApplication application;

    @BeforeEach
    void setUp() {
        store = new InMemoryNotificationStore();
        application = new NotificationApplication(store, clock);
        seed("product_audit.passed", "intent-1", 7L, "商品已通过审核");
        seed("product_audit.rejected", "intent-2", 7L, "商品未通过审核");
        seed("trade.request_accepted", "intent-3", 7L, "卖家已接受购买请求");
    }

    @Test
    void listsOnlyTheReadersOwnNotificationsNewestFirst() {
        var queries = new NotificationQueries(store, Optional.of((context, facts) ->
                Optional.of(new NotificationSourcePort.NotificationSourceView("摘要", PRODUCT))));

        var page = queries.list(context(READER), NotificationQuery.firstPage());

        assertThat(page.items()).hasSize(3);
        assertThat(page.total()).isEqualTo(3);
        assertThat(page.items()).extracting(NotificationView::notificationId).isSortedAccordingTo(
                java.util.Comparator.reverseOrder());
    }

    @Test
    void reportsTheUnreadTotalIndependentlyOfTheReadFilter() {
        var queries = new NotificationQueries(store, Optional.empty());
        markAllButOneRead();

        var unreadPage = queries.list(context(READER),
                new NotificationQuery(1, 20, NotificationQuery.ReadFilter.UNREAD, null));
        var allPage = queries.list(context(READER), NotificationQuery.firstPage());

        assertThat(unreadPage.unreadCount()).isEqualTo(allPage.unreadCount());
        assertThat(allPage.unreadCount()).isEqualTo(1);
        assertThat(unreadPage.total()).isEqualTo(1);
        assertThat(allPage.total()).isEqualTo(3);
    }

    @Test
    void appliesTheEventFilterBeforePaging() {
        var queries = new NotificationQueries(store, Optional.empty());

        var page = queries.list(context(READER),
                new NotificationQuery(1, 1, NotificationQuery.ReadFilter.ALL, "product_audit.rejected"));

        assertThat(page.total()).isEqualTo(1);
        assertThat(page.items()).hasSize(1);
        assertThat(page.items().getFirst().eventType()).isEqualTo("product_audit.rejected");
    }

    @Test
    void hidesTheJumpTargetAndKeepsOnlyTheHintWhenTheSourceIsNotVisible() {
        var queries = new NotificationQueries(store, Optional.empty());

        var view = queries.get(context(READER), newestNotificationId());

        assertThat(view.summary()).isEqualTo(NotificationQueries.HIDDEN_SOURCE_SUMMARY);
        assertThat(view.source()).isNull();
        assertThat(view.subject()).isNull();
        assertThat(view.body()).isNull();
    }

    @Test
    void usesTheSourceProjectionWordingAndJumpTargetWhenVisible() {
        var queries = new NotificationQueries(store, Optional.of((context, facts) ->
                Optional.of(new NotificationSourcePort.NotificationSourceView(
                        "商品《高等数学》已通过审核", facts.source()))));

        var view = queries.get(context(READER), newestNotificationId());

        assertThat(view.summary()).isEqualTo("商品《高等数学》已通过审核");
        assertThat(view.source()).isEqualTo(PRODUCT);
    }

    @Test
    void refusesToReadAnotherAccountsNotification() {
        var queries = new NotificationQueries(store, Optional.empty());

        assertThatThrownBy(() -> queries.get(context(9L), newestNotificationId()))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
    }

    @Test
    void refusesANotificationThatDoesNotExist() {
        var queries = new NotificationQueries(store, Optional.empty());

        assertThatThrownBy(() -> queries.get(context(READER), 9_999L))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).status()).isEqualTo(404));
    }

    @Test
    void refusesAGuestActor() {
        var queries = new NotificationQueries(store, Optional.empty());
        var guest = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ENTRY, "entry-1", null,
                null, null, "test");

        assertThatThrownBy(() -> queries.list(guest, NotificationQuery.firstPage()))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code()).isEqualTo("AUTHENTICATION_REQUIRED"));
    }

    private void markAllButOneRead() {
        long newest = newestNotificationId();
        store.page(READER, NotificationQuery.ReadFilter.ALL, null, 1, 50).stream()
                .filter(row -> row.notificationId() != newest)
                .forEach(row -> application.markRead(mockTransaction(), READER, row.notificationId()));
    }

    private long newestNotificationId() {
        return store.page(READER, NotificationQuery.ReadFilter.ALL, null, 1, 1).getFirst().notificationId();
    }

    private void seed(String eventType, String intentKey, long recipient, String ignoredSummary) {
        var intent = new NotificationIntent(Set.of(recipient), null, eventType, PRODUCT, intentKey,
                "template", "1", Map.of("hint", ignoredSummary), OCCURRED);
        application.createNotifications(mockTransaction(), intent);
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                UUID.randomUUID(), null, 0L, "test");
    }

    private static io.github.iy88.project1.core.WriteTransaction mockTransaction() {
        return org.mockito.Mockito.mock(io.github.iy88.project1.core.WriteTransaction.class);
    }
}
