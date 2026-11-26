package io.github.iy88.project1.api.account;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountTradeService;
import io.github.iy88.project1.api.PageSettings;
import io.github.iy88.project1.casemanagement.application.CaseOwnedReadModel;
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
    private static final Map<String, Long> EMPTY_COUNTS = Map.of(
            "request_response", 0L, "agreement_response", 0L, "completion_response", 0L,
            "cancellation_response", 0L, "inquiry_response", 0L);

    private final ProductService products = mock(ProductService.class);
    private final ProductInteractions interactions = mock(ProductInteractions.class);
    private final TradeOwnedReadModel trades = mock(TradeOwnedReadModel.class);
    private final TradeReviewReadModel reviews = mock(TradeReviewReadModel.class);
    private final AccountTradeService accountTrades = mock(AccountTradeService.class);
    private final CaseOwnedReadModel cases = mock(CaseOwnedReadModel.class);
    private final OwnedTodoQueries ownedTodos = mock(OwnedTodoQueries.class);
    private AccountOwnedQueries queries;

    @BeforeEach
    void setUp() {
        queries = new AccountOwnedQueries(products, interactions, trades, reviews, accountTrades, cases,
                ownedTodos, new PageSettings(20, 100), Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void overviewAggregatesReportCountsAndInquiryTodosInOneComposition() {
        when(products.myCounts(ACCOUNT)).thenReturn(new ProductService.ProductCounts(3,
                Map.of("public", 2L, "off_shelf", 1L)));
        when(interactions.favoriteCounts(ACCOUNT)).thenReturn(new ProductInteractions.FavoriteCounts(4, 3, 1));
        when(trades.totals(ACCOUNT)).thenReturn(new TradeOwnedReadModel.TradeTotals(5, 3, 2,
                Map.of("in_progress", 2L, "completed", 3L)));
        when(reviews.counts(ACCOUNT)).thenReturn(new TradeReviewReadModel.EvaluationCounts(2, 1));
        when(cases.reportCounts(ACCOUNT)).thenReturn(new CaseOwnedReadModel.ReportCounts(3, 2));
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, false));
        when(trades.todoCount(ACCOUNT, true)).thenReturn(2L);
        when(cases.inquiryTodoCount(ACCOUNT)).thenReturn(4L);

        var overview = queries.overview(ACCOUNT);

        assertThat(overview.asOf()).isEqualTo(NOW);
        assertThat(overview.products().total()).isEqualTo(3);
        assertThat(overview.trades().byState()).containsEntry("completed", 3L);
        assertThat(overview.favorites()).isEqualTo(new AccountOwnedQueries.FavoriteOverview(4, 3, 1));
        assertThat(overview.evaluations()).isEqualTo(new AccountOwnedQueries.EvaluationOverview(2, 1));
        assertThat(overview.reports()).isEqualTo(new AccountOwnedQueries.ReportOverview(3, 2));
        assertThat(overview.todoCount()).isEqualTo(6);
    }

    @Test
    void todosExposeTheStableKeyAndSourceAction() {
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, false));
        when(ownedTodos.todos(ACCOUNT, null, true, 20, 0L)).thenReturn(new OwnedTodoQueries.Page(
                List.of(new OwnedTodoQueries.Candidate("agreement_response", 31L, 12L, 31L, null, null,
                        null, null, NOW.minusSeconds(60), NOW.minusSeconds(30), 4L, "旧书")), 1,
                Map.of("request_response", 0L, "agreement_response", 1L, "completion_response", 0L,
                        "cancellation_response", 0L, "inquiry_response", 0L)));

        var page = queries.todos(ACCOUNT, null, 1, 20);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.todoKey()).isEqualTo("agreement_response:8:31");
            assertThat(item.source()).containsEntry("trade_id", "12").containsEntry("agreement_id", "31");
            assertThat(item.summary()).contains("旧书");
        });
        assertThat(page.total()).isEqualTo(1);
    }

    @Test
    void inquiryTodosKeepOneCaseRowWithStableActionIds() {
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, true));
        when(ownedTodos.todos(ACCOUNT, "inquiry_response", false, 20, 0L)).thenReturn(
                new OwnedTodoQueries.Page(List.of(new OwnedTodoQueries.Candidate("inquiry_response", 6L,
                        null, null, null, null, 6L, "4,9", NOW.minusSeconds(60), NOW.minusSeconds(10),
                        null, null)), 1, Map.of("inquiry_response", 1L)));

        var page = queries.todos(ACCOUNT, "inquiry_response", 1, 20);

        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.todoKey()).isEqualTo("inquiry_response:8:6");
            assertThat(item.source()).containsEntry("case_id", "6");
            assertThat(item.source()).containsEntry("inquiry_action_ids", List.of("4", "9"));
            assertThat(item.summary()).contains("管理问询").doesNotContain("举报人");
        });
        assertThat(page.total()).isEqualTo(1);
    }

    @Test
    void unknownTodoKindIsRejectedButInquiryIsNoLonger503() {
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
        assertThatThrownBy(() -> queries.reportResources(ACCOUNT, null, null, 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        assertThatThrownBy(() -> queries.reportResources(ACCOUNT, "written", "unknown", 1, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        assertThatThrownBy(() -> queries.todos(ACCOUNT, null, 0, 20))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("INPUT_INVALID"));
    }

    @Test
    void reportResourcesExposeOnlyTheContractFields() {
        when(cases.reports(ACCOUNT, "received", "decided", 20, 0L)).thenReturn(
                new CaseOwnedReadModel.ReportPage(List.of(new CaseOwnedReadModel.ReportRow(6L, "received",
                        "decided", NOW.minusSeconds(5), "事项已作出处理决定")), 1));

        var page = queries.reportResources(ACCOUNT, "received", "DECIDED", 1, 20);

        assertThat(page.kind()).isEqualTo("report");
        assertThat(page.asOf()).isEqualTo(NOW);
        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.caseId()).isEqualTo("6");
            assertThat(item.direction()).isEqualTo("received");
            assertThat(item.state()).isEqualTo("decided");
            assertThat(item.summary()).isEqualTo("事项已作出处理决定");
        });
    }

    @Test
    void restrictedAccountKeepsInquiryTodosButLosesTradeTodos() {
        when(accountTrades.qualification(ACCOUNT)).thenReturn(new AccountTradeService.Qualification(true, true));
        when(ownedTodos.todos(ACCOUNT, null, false, 20, 0L)).thenReturn(
                new OwnedTodoQueries.Page(List.of(), 0, EMPTY_COUNTS));

        var page = queries.todos(ACCOUNT, null, 1, 20);

        assertThat(page.items()).isEmpty();
        verify(ownedTodos).todos(ACCOUNT, null, false, 20, 0L);
    }
}
