package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.AccountTradeService;
import io.github.iy88.project1.api.PageSettings;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CaseOwnedReadModel;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.application.ProductService;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import io.github.iy88.project1.trade.application.TradeReviewReadModel;
import io.github.iy88.project1.trade.domain.TradeStatus;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Account-owned aggregation for API-COM-QUERY-001/002/003.
 *
 * <p>Every method runs in one short read-only repeatable-read snapshot. The product, trade,
 * review and case modules return already-filtered, already-counted facts, so this class never
 * loads full views, signs files or fans out per item.
 */
@Service
@Profile("infrastructure")
public class AccountOwnedQueries {
    private static final List<String> TODO_KINDS = OwnedTodoQueries.TODO_KINDS;
    private static final Set<String> ROLES = Set.of("all", "buying", "selling");
    private static final Set<String> DIRECTIONS = Set.of("written", "received");
    private static final Set<String> REPORT_STATES = Set.of(CaseVocabulary.PENDING, CaseVocabulary.CLAIMED,
            CaseVocabulary.DECIDED);

    private final ProductService products;
    private final ProductInteractions interactions;
    private final TradeOwnedReadModel trades;
    private final TradeReviewReadModel reviews;
    private final AccountTradeService accountTrades;
    private final CaseOwnedReadModel cases;
    private final OwnedTodoQueries ownedTodos;
    private final PageSettings pages;
    private final Clock clock;

    public AccountOwnedQueries(ProductService products, ProductInteractions interactions, TradeOwnedReadModel trades,
                               TradeReviewReadModel reviews, AccountTradeService accountTrades,
                               CaseOwnedReadModel cases, OwnedTodoQueries ownedTodos, PageSettings pages,
                               Clock clock) {
        this.products = products;
        this.interactions = interactions;
        this.trades = trades;
        this.reviews = reviews;
        this.accountTrades = accountTrades;
        this.cases = cases;
        this.ownedTodos = ownedTodos;
        this.pages = pages;
        this.clock = clock;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public MyOverview overview(long accountId) {
        Instant asOf = clock.instant();
        var productCounts = products.myCounts(accountId);
        var favoriteCounts = interactions.favoriteCounts(accountId);
        var tradeCounts = trades.totals(accountId);
        var evaluationCounts = reviews.counts(accountId);
        var reportCounts = cases.reportCounts(accountId);
        var qualification = accountTrades.qualification(accountId);
        long todoCount = trades.todoCount(accountId,
                qualification.exists() && !qualification.writeRestricted())
                + cases.inquiryTodoCount(accountId);
        return new MyOverview(asOf, new ProductOverview(productCounts.total(), productCounts.byState()),
                new TradeOverview(tradeCounts.total(), tradeCounts.buying(), tradeCounts.selling(),
                        tradeCounts.byState()),
                new FavoriteOverview(favoriteCounts.total(), favoriteCounts.valid(), favoriteCounts.invalid()),
                new EvaluationOverview(evaluationCounts.written(), evaluationCounts.received()),
                new ReportOverview(reportCounts.submitted(), reportCounts.received()), todoCount);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public MyTodoPage todos(long accountId, String kind, Integer page, Integer pageSize) {
        int[] paging = paging(page, pageSize);
        String normalizedKind = validateTodoKind(kind);
        var qualification = accountTrades.qualification(accountId);
        boolean writable = qualification.exists() && !qualification.writeRestricted();
        var result = ownedTodos.todos(accountId, normalizedKind, writable, paging[1],
                (long) (paging[0] - 1) * paging[1]);
        List<TodoView> items = new ArrayList<>();
        for (OwnedTodoQueries.Candidate row : result.items()) {
            items.add(todoView(accountId, row));
        }
        return new MyTodoPage(items, paging[0], paging[1], result.total(), result.countsByKind(),
                clock.instant());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public TradeResources tradeResources(long accountId, String role, String state, Integer page, Integer pageSize) {
        int[] paging = paging(page, pageSize);
        String normalizedRole = role == null || role.isBlank() ? "all" : role.trim();
        if (!ROLES.contains(normalizedRole)) {
            throw new BusinessError("INPUT_INVALID", 422, "role 参数无效");
        }
        String normalizedState = tradeState(state);
        var result = trades.resources(accountId, normalizedRole, normalizedState, paging[1],
                (long) (paging[0] - 1) * paging[1]);
        List<TradeResourceItem> items = result.items().stream()
                .map(row -> new TradeResourceItem(Long.toString(row.tradeId()), row.role(), row.state(),
                        row.updatedAt(), row.productTitle() == null ? null
                        : new ProductSummary(Long.toString(row.productId()), row.productTitle(),
                        row.priceCents() == null ? 0 : row.priceCents())))
                .toList();
        return new TradeResources("trade", items, paging[0], paging[1], result.total(), clock.instant());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public EvaluationResources evaluationResources(long accountId, String direction, Integer page,
                                                   Integer pageSize) {
        int[] paging = paging(page, pageSize);
        String normalized = direction == null ? "" : direction.trim();
        if (!DIRECTIONS.contains(normalized)) {
            throw new BusinessError("INPUT_INVALID", 422, "direction 参数无效");
        }
        var result = reviews.page(accountId, normalized, paging[1], (long) (paging[0] - 1) * paging[1]);
        List<EvaluationItem> items = result.items().stream()
                .map(row -> new EvaluationItem(Long.toString(row.evaluationId()), Long.toString(row.tradeId()),
                        row.direction(), row.createdAt(), row.createdAt(), row.content()))
                .toList();
        return new EvaluationResources("evaluation", items, paging[0], paging[1], result.total(),
                clock.instant());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ReportResources reportResources(long accountId, String direction, String state, Integer page,
                                           Integer pageSize) {
        int[] paging = paging(page, pageSize);
        String normalizedDirection = direction == null ? "" : direction.trim().toLowerCase(Locale.ROOT);
        if (!DIRECTIONS.contains(normalizedDirection)) {
            throw new BusinessError("INPUT_INVALID", 422, "direction 参数无效");
        }
        String normalizedState = reportState(state);
        var result = cases.reports(accountId, normalizedDirection, normalizedState, paging[1],
                (long) (paging[0] - 1) * paging[1]);
        List<ReportResourceItem> items = result.items().stream()
                .map(row -> new ReportResourceItem(Long.toString(row.caseId()), row.direction(), row.state(),
                        row.updatedAt(), row.summary()))
                .toList();
        return new ReportResources("report", items, paging[0], paging[1], result.total(), clock.instant());
    }

    private int[] paging(Integer page, Integer pageSize) {
        int current = page == null ? 1 : page;
        int size = pageSize == null ? pages.pageSizeDefault() : pageSize;
        if (current < 1 || size < 1 || size > pages.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        return new int[]{current, size};
    }

    private static String validateTodoKind(String kind) {
        if (kind == null || kind.isBlank()) {
            return null;
        }
        String normalized = kind.trim();
        if (!TODO_KINDS.contains(normalized)) {
            throw new BusinessError("INPUT_INVALID", 422, "待办类型无效");
        }
        return normalized;
    }

    private static String reportState(String state) {
        if (state == null || state.isBlank()) {
            return null;
        }
        String normalized = state.trim().toLowerCase(Locale.ROOT);
        if (!REPORT_STATES.contains(normalized)) {
            throw new BusinessError("INPUT_INVALID", 422, "举报状态无效");
        }
        return normalized;
    }

    private static String tradeState(String state) {
        if (state == null || state.isBlank()) {
            return null;
        }
        String normalized = state.trim().toLowerCase(Locale.ROOT);
        try {
            return TradeStatus.from(normalized).value();
        } catch (IllegalArgumentException invalid) {
            throw new BusinessError("INPUT_INVALID", 422, "交易状态无效");
        }
    }

    private static TodoView todoView(long accountId, OwnedTodoQueries.Candidate row) {
        if ("inquiry_response".equals(row.kind())) {
            Map<String, Object> source = new LinkedHashMap<>();
            source.put("case_id", Long.toString(row.caseId()));
            source.put("inquiry_action_ids", inquiryIds(row.inquiryActionIds()));
            String todoKey = row.kind() + ":" + accountId + ":" + row.caseId();
            String summary = "事项 #" + row.caseId() + " 有管理问询等待你回复";
            return new TodoView(todoKey, row.kind(), source, row.createdAt(), row.updatedAt(), summary);
        }
        return todoView(accountId, new TradeOwnedReadModel.TodoRow(row.kind(), row.sourceId(), row.tradeId(),
                row.agreementId(), row.confirmationId(), row.cancellationId(), row.createdAt(), row.updatedAt(),
                row.productId(), row.title()));
    }

    private static TodoView todoView(long accountId, TradeOwnedReadModel.TodoRow row) {
        String title = row.productTitle() == null || row.productTitle().isBlank()
                ? "交易 " + row.tradeId() : "《" + row.productTitle() + "》";
        String summary = switch (row.kind()) {
            case "request_response" -> title + "有新的购买请求待处理";
            case "agreement_response" -> title + "的约定等待你回应";
            case "completion_response" -> title + "对方已提交完成确认，等待你确认";
            case "cancellation_response" -> title + "对方提出取消交易";
            default -> title + "有新的待处理事项";
        };
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("trade_id", Long.toString(row.tradeId()));
        if (row.agreementId() != null) {
            source.put("agreement_id", Long.toString(row.agreementId()));
        }
        if (row.confirmationId() != null) {
            source.put("confirmation_id", Long.toString(row.confirmationId()));
        }
        if (row.cancellationId() != null) {
            source.put("cancellation_id", Long.toString(row.cancellationId()));
        }
        String todoKey = row.kind() + ":" + accountId + ":" + row.sourceId();
        return new TodoView(todoKey, row.kind(), source, row.createdAt(), row.updatedAt(), summary);
    }

    private static List<String> inquiryIds(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        return java.util.Arrays.stream(value.split(","))
                .map(String::trim)
                .filter(id -> !id.isEmpty())
                .toList();
    }

    public record MyOverview(Instant asOf, ProductOverview products, TradeOverview trades,
                             FavoriteOverview favorites, EvaluationOverview evaluations,
                             ReportOverview reports, long todoCount) {
    }

    public record ProductOverview(long total, Map<String, Long> byState) {
        public ProductOverview {
            byState = Map.copyOf(byState);
        }
    }

    public record TradeOverview(long total, long buying, long selling, Map<String, Long> byState) {
        public TradeOverview {
            byState = Map.copyOf(byState);
        }
    }

    public record FavoriteOverview(long total, long valid, long invalid) {
    }

    public record EvaluationOverview(long written, long received) {
    }

    public record ReportOverview(long submitted, long received) {
    }

    public record MyTodoPage(List<TodoView> items, int page, int pageSize, long total,
                             Map<String, Long> countsByKind, Instant asOf) {
        public MyTodoPage {
            items = List.copyOf(items);
            countsByKind = Map.copyOf(countsByKind);
        }
    }

    public record TodoView(String todoKey, String kind, Map<String, Object> source, Instant createdAt,
                           Instant updatedAt, String summary) {
        public TodoView {
            source = Map.copyOf(source);
        }
    }

    public record TradeResources(String kind, List<TradeResourceItem> items, int page, int pageSize, long total,
                                 Instant asOf) {
        public TradeResources {
            items = List.copyOf(items);
        }
    }

    public record TradeResourceItem(String tradeId, String role, String state, Instant updatedAt,
                                    ProductSummary productSummary) {
    }

    public record ProductSummary(String productId, String title, long priceCents) {
    }

    public record EvaluationResources(String kind, List<EvaluationItem> items, int page, int pageSize, long total,
                                      Instant asOf) {
        public EvaluationResources {
            items = List.copyOf(items);
        }
    }

    public record EvaluationItem(String evaluationId, String tradeId, String direction, Instant createdAt,
                                 Instant updatedAt, String content) {
    }

    public record ReportResources(String kind, List<ReportResourceItem> items, int page, int pageSize, long total,
                                  Instant asOf) {
        public ReportResources {
            items = List.copyOf(items);
        }
    }

    public record ReportResourceItem(String caseId, String direction, String state, Instant updatedAt,
                                     String summary) {
    }
}
