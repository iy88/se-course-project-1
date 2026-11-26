package io.github.iy88.project1.api.account;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountTradeService;
import io.github.iy88.project1.api.PageSettings;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.application.ProductService;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import io.github.iy88.project1.trade.application.TradeReviewReadModel;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class AccountOwnedQueriesTests {
    private static final long ACCOUNT = 8L;
    private static final Instant NOW = Instant.parse("2026-11-23T03:00:00Z");

    private final ProductService products = mock(ProductService.class);
    private final ProductInteractions interactions = mock(ProductInteractions.class);
    private final TradeOwnedReadModel trades = mock(TradeOwnedReadModel.class);
    private final TradeReviewReadModel reviews = mock(TradeReviewReadModel.class);
    private final AccountTradeService accountTrades = mock(AccountTradeService.class);
    private AccountOwnedQueries queries;

    @BeforeEach
    void setUp() {
        queries = new AccountOwnedQueries(products, interactions, trades, reviews, accountTrades,
                new PageSettings(20, 100), Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void overviewUsesOneCompositionAndKeepsReportFieldsAtZero() {
        when(products.myCounts(ACCOUNT)).thenReturn(new ProductService.ProductCounts(3,
                Map.of("public", 2L, "off_shelf", 1L)));
        when(interactions.favoriteCounts(ACCOUNT)).thenReturn(new ProductInteractions.FavoriteCounts(4, 3, 1));
        when(trades.totals(ACCOUNT)).thenReturn(new TradeOwnedReadModel.TradeTotals(5, 3, 2,
                Map.of("in_progress", 2L, "completed", 3L)));
        when(reviews.counts(ACCOUNT)).thenReturn(new TradeReviewReadModel.EvaluationCounts(2, 1));
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, false));
        when(trades.todoCount(ACCOUNT, true)).thenReturn(2L);

        var overview = queries.overview(ACCOUNT);

        assertThat(overview.asOf()).isEqualTo(NOW);
        assertThat(overview.products().total()).isEqualTo(3);
        assertThat(overview.trades().byState()).containsEntry("completed", 3L);
        assertThat(overview.favorites()).isEqualTo(new AccountOwnedQueries.FavoriteOverview(4, 3, 1));
        assertThat(overview.evaluations()).isEqualTo(new AccountOwnedQueries.EvaluationOverview(2, 1));
        assertThat(overview.reports()).isEqualTo(new AccountOwnedQueries.ReportOverview(0, 0));
        assertThat(overview.todoCount()).isEqualTo(2);
    }

    @Test
    void todosExposeTheStableKeyAndSourceAction() {
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, false));
        when(trades.todos(ACCOUNT, null, true, 20, 0L)).thenReturn(new TradeOwnedReadModel.TodoPage(
                List.of(new TradeOwnedReadModel.TodoRow("agreement_response", 31L, 12L, 31L, null, null,
                        NOW.minusSeconds(60), NOW.minusSeconds(30), 4L, "旧书")), 1,
                Map.of("request_response", 0L, "agreement_response", 1L, "completion_response", 0L,
                        "cancellation_response", 0L)));

        var page = queries.todos(ACCOUNT, null, 1, 20);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.todoKey()).isEqualTo("agreement_response:8:31");
            assertThat(item.source()).containsEntry("trade_id", "12").containsEntry("agreement_id", "31");
            assertThat(item.summary()).contains("旧书");
        });
        assertThat(page.total()).isEqualTo(1);
    }

    @Test
    void inquiryTodosAndUnknownKindsDoNotBecomeEmptyLists() {
        assertThatThrownBy(() -> queries.todos(ACCOUNT, "inquiry_response", 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("DEPENDENCY_UNAVAILABLE"));
        assertThatThrownBy(() -> queries.todos(ACCOUNT, "unknown", 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }

    @Test
    void invalidTradeRoleStateAndDirectionAreRejectedBeforeQuerying() {
        assertThatThrownBy(() -> queries.tradeResources(ACCOUNT, "owner", null, 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        assertThatThrownBy(() -> queries.tradeResources(ACCOUNT, "all", "unknown", 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        assertThatThrownBy(() -> queries.evaluationResources(ACCOUNT, null, 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        assertThatThrownBy(() -> queries.todos(ACCOUNT, null, 0, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }

    @Test
    void restrictedAccountKeepsHistoryButHasNoTodoCandidates() {
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, true));
        when(trades.todos(ACCOUNT, null, false, 20, 0L)).thenReturn(new TradeOwnedReadModel.TodoPage(
                List.of(), 0, Map.of("request_response", 0L, "agreement_response", 0L,
                "completion_response", 0L, "cancellation_response", 0L)));

        var page = queries.todos(ACCOUNT, null, 1, 20);

        assertThat(page.items()).isEmpty();
        verify(trades).todos(ACCOUNT, null, false, 20, 0L);
    }
}
