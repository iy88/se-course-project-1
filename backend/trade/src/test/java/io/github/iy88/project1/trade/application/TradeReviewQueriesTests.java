package io.github.iy88.project1.trade.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class TradeReviewQueriesTests {
    private static final long BUYER = 8001;
    private static final long SELLER = 8002;
    private static final long TRADE_ID = 9001;
    private static final Instant NOW = Instant.parse("2026-11-25T00:00:00Z");

    private TradeRepository repository;
    private TradePorts.Accounts accounts;
    private TradeApplication application;

    @BeforeEach
    void setUp() {
        repository = mock(TradeRepository.class);
        accounts = mock(TradePorts.Accounts.class);
        application = new TradeApplication(repository, mock(WriteExecutor.class), mock(TaskSchedules.class),
                Clock.fixed(NOW, ZoneOffset.UTC), new TradeSettings(604800, "s3-v1", 20, 100, 200),
                mock(TradePorts.Product.class), accounts, mock(TradePorts.Conversation.class),
                mock(TradePorts.Cases.class), mock(TradePorts.Notifications.class),
                JsonMapper.builder().build());
    }

    @Test
    void tradeReviewsExposeTheServerComputedEligibilityAndHideRemovedContent() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.COMPLETED)));
        when(repository.review(TRADE_ID, BUYER))
                .thenReturn(Optional.of(review(11, BUYER, SELLER, 5, "buyer review", true)));
        when(repository.review(TRADE_ID, SELLER))
                .thenReturn(Optional.of(review(12, SELLER, BUYER, 4, "hidden content", false)));
        when(accounts.profiles(Set.of(BUYER, SELLER))).thenReturn(Map.of(
                BUYER, new TradePorts.AccountProfile(BUYER, "buyer", "https://img/buyer"),
                SELLER, new TradePorts.AccountProfile(SELLER, "seller", null)));
        when(accounts.qualification(BUYER)).thenReturn(new TradePorts.AccountQualification(BUYER, true, false));

        var view = application.getTradeReviews(context(BUYER), TRADE_ID);

        assertThat(view.path("can_review").asBoolean()).isFalse();
        assertThat(view.path("written").path("review_id").stringValue()).isEqualTo("11");
        assertThat(view.path("written").path("content").stringValue()).isEqualTo("buyer review");
        assertThat(view.path("received").path("review_id").stringValue()).isEqualTo("12");
        assertThat(view.path("received").path("visible").asBoolean()).isFalse();
        assertThat(view.path("received").path("content").isNull()).isTrue();
        assertThat(view.path("received").path("reviewer").path("display_name").stringValue())
                .isEqualTo("seller");
    }

    @Test
    void myReviewsUseTheDatabaseDirectionFilterAndTotal() {
        when(repository.pageReviews(BUYER, "written", 20, 0))
                .thenReturn(new TradeRepository.ReviewPage(List.of(
                        review(21, BUYER, SELLER, 5, "first", true),
                        review(20, BUYER, SELLER, 3, "second", true)), 2));
        when(accounts.profiles(Set.of(BUYER, SELLER))).thenReturn(Map.of(
                BUYER, new TradePorts.AccountProfile(BUYER, "buyer", null),
                SELLER, new TradePorts.AccountProfile(SELLER, "seller", null)));

        var view = application.listMyReviews(context(BUYER), "written", 1, 20);

        assertThat(view.path("total").asLong()).isEqualTo(2);
        assertThat(view.at("/items/0/review_id").stringValue()).isEqualTo("21");
        assertThat(view.at("/items/1/review_id").stringValue()).isEqualTo("20");
        assertThat(view.path("page").asInt()).isEqualTo(1);
        assertThat(view.path("page_size").asInt()).isEqualTo(20);
    }

    @Test
    void reviewEligibilityRejectsAnExistingReviewOrRestrictedAccount() {
        when(repository.find(TRADE_ID)).thenReturn(Optional.of(trade(TradeStatus.COMPLETED)));
        when(repository.review(TRADE_ID, BUYER)).thenReturn(Optional.of(
                review(31, BUYER, SELLER, 5, "already", true)));
        when(accounts.qualification(BUYER))
                .thenReturn(new TradePorts.AccountQualification(BUYER, true, false));

        var reviewed = application.reviewEligibility(TRADE_ID, BUYER);
        assertThat(reviewed.eligible()).isFalse();
        assertThat(reviewed.reason()).isEqualTo("already_reviewed");

        when(repository.review(TRADE_ID, BUYER)).thenReturn(Optional.empty());
        when(accounts.qualification(BUYER))
                .thenReturn(new TradePorts.AccountQualification(BUYER, true, true));
        var restricted = application.reviewEligibility(TRADE_ID, BUYER);
        assertThat(restricted.eligible()).isFalse();
        assertThat(restricted.reason()).isEqualTo("account_write_restricted");
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), UUID.randomUUID(), null, 1L, "review-query-test");
    }

    private static Trade trade(TradeStatus status) {
        return new Trade(TRADE_ID, 7001, BUYER, SELLER, status, null, null, 3, null,
                status == TradeStatus.COMPLETED ? "completed" : null, NOW.minusSeconds(20), null,
                status.isTerminal() ? NOW : null, NOW.minusSeconds(30), NOW);
    }

    private static TradeModels.Review review(long id, long reviewer, long reviewee, int rating,
                                             String content, boolean visible) {
        return new TradeModels.Review(id, TRADE_ID, reviewer, reviewee, rating, content, visible, NOW);
    }
}
