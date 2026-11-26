package io.github.iy88.project1.trade.application;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Trade-owned read projections for the account aggregation (API-COM-QUERY-001/002/003), product
 * edit notices and the buyer edit-history scope.
 *
 * <p>The queries use exactly the trade predicate of {@link io.github.iy88.project1.trade.domain.Trade}
 * for the current actions. Filtering, counting and paging happen in SQL so callers never load a full
 * {@code TradeView}, sign files or fan out per row.
 */
@Service
@Profile("infrastructure")
public class TradeOwnedReadModel {
    private static final List<String> TODO_KINDS = List.of("request_response", "agreement_response",
            "completion_response", "cancellation_response");

    /**
     * One current todo. {@code sourceId} is the immutable sub-event id for kinds with one, or the
     * trade id for the request itself.
     */
    public record TodoRow(String kind, long sourceId, long tradeId, Long agreementId, Long confirmationId,
                          Long cancellationId, Instant createdAt, Instant updatedAt, Long productId,
                          String productTitle) {
    }

    public record TodoPage(List<TodoRow> items, long total, Map<String, Long> countsByKind) {
        public TodoPage {
            items = List.copyOf(items);
            countsByKind = Map.copyOf(countsByKind);
        }
    }

    public record TradeTotals(long total, long buying, long selling, Map<String, Long> byState) {
        public TradeTotals {
            byState = Map.copyOf(byState);
        }
    }

    public record TradeResourceRow(long tradeId, String role, String state, Instant updatedAt, long productId,
                                   String productTitle, Long priceCents) {
    }

    public record TradeResourcePage(List<TradeResourceRow> items, long total) {
        public TradeResourcePage {
            items = List.copyOf(items);
        }
    }

    /** Active (not ended) trade whose buyer must learn about one product edit. */
    public record ProductNoticeTarget(long tradeId, long buyerId, String productTitle) {
    }

    public record ProductNoticeContext(String productTitle, String requestNote) {
    }

    private final JdbcClient jdbc;

    public TradeOwnedReadModel(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public TradeTotals totals(long accountId) {
        var rows = jdbc.sql("""
                        select status, count(*) as total,
                               count(*) filter (where buyer_id = :account) as buying,
                               count(*) filter (where seller_id = :account) as selling
                          from trade
                         where buyer_id = :account or seller_id = :account
                         group by status
                         order by status
                        """)
                .param("account", accountId)
                .query((row, index) -> new StatusCount(row.getString("status"), row.getLong("total"),
                        row.getLong("buying"), row.getLong("selling")))
                .list();
        long total = 0;
        long buying = 0;
        long selling = 0;
        Map<String, Long> byState = new LinkedHashMap<>();
        for (StatusCount row : rows) {
            total += row.total();
            buying += row.buying();
            selling += row.selling();
            byState.put(row.status(), row.total());
        }
        return new TradeTotals(total, buying, selling, byState);
    }

    public TradeResourcePage resources(long accountId, String role, String state, int limit, long offset) {
        var where = new StringBuilder(" where (t.buyer_id = :account or t.seller_id = :account)");
        if ("buying".equals(role)) {
            where.append(" and t.buyer_id = :account");
        } else if ("selling".equals(role)) {
            where.append(" and t.seller_id = :account");
        }
        if (state != null) {
            where.append(" and t.status = :state");
        }
        String from = """
                  from trade t
                  left join trade_item_snapshot s on s.trade_id = t.id
                  left join product p on p.product_id = t.product_id
                """;
        String selection = """
                select t.id as trade_id,
                       case when t.buyer_id = :account then 'buyer' else 'seller' end as role,
                       t.status, t.updated_at, t.product_id,
                       coalesce(s.title, case
                           when p.deleted_at is null
                                and (p.lifecycle_state in ('public', 'in_trade') or t.seller_id = :account)
                           then p.title end) as product_title,
                       case when s.trade_id is not null then s.price_cents
                            when p.deleted_at is null
                                 and (p.lifecycle_state in ('public', 'in_trade') or t.seller_id = :account)
                            then p.price_cents end as price_cents
                """;
        var page = jdbc.sql(selection + from + where
                        + " order by t.updated_at desc, t.id desc limit :limit offset :offset")
                .param("account", accountId).param("limit", limit).param("offset", offset);
        var count = jdbc.sql("select count(*)" + from + where).param("account", accountId);
        if (state != null) {
            page = page.param("state", state);
            count = count.param("state", state);
        }
        List<TradeResourceRow> items = page
                .query((row, index) -> new TradeResourceRow(row.getLong("trade_id"), row.getString("role"),
                        row.getString("status"), instant(row, "updated_at"), row.getLong("product_id"),
                        row.getString("product_title"), nullableLong(row, "price_cents")))
                .list();
        return new TradeResourcePage(items, count.query(Long.class).single());
    }

    /**
     * Current trade todos under the same predicate used by {@code Trade.allowedActions}.
     *
     * @param writable false for a restricted/absent account; no candidate is then returned
     */
    public TodoPage todos(long accountId, String kind, boolean writable, int limit, long offset) {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String candidate : TODO_KINDS) {
            counts.put(candidate, 0L);
        }
        if (!writable) {
            return new TodoPage(List.of(), 0, counts);
        }
        var countRows = jdbc.sql(TODO_CANDIDATES + " select kind, count(*) as total from candidate group by kind")
                .param("account", accountId).param("writable", true)
                .query((row, index) -> new KindCount(row.getString("kind"), row.getLong("total")))
                .list();
        for (KindCount row : countRows) {
            counts.put(row.kind(), row.total());
        }
        String filter = kind == null ? "" : " where kind = :kind";
        var page = jdbc.sql(TODO_CANDIDATES + " select * from candidate" + filter
                        + " order by updated_at desc, kind asc, source_id desc limit :limit offset :offset")
                .param("account", accountId).param("writable", true)
                .param("limit", limit).param("offset", offset);
        var total = jdbc.sql(TODO_CANDIDATES + " select count(*) from candidate" + filter)
                .param("account", accountId).param("writable", true);
        if (kind != null) {
            page = page.param("kind", kind);
            total = total.param("kind", kind);
        }
        List<TodoRow> items = page.query((row, index) -> new TodoRow(row.getString("kind"),
                        row.getLong("source_id"), row.getLong("trade_id"), nullableLong(row, "agreement_id"),
                        nullableLong(row, "confirmation_id"), nullableLong(row, "cancellation_id"),
                        instant(row, "created_at"), instant(row, "updated_at"), nullableLong(row, "product_id"),
                        row.getString("title")))
                .list();
        return new TodoPage(items, total.query(Long.class).single(), counts);
    }

    public long todoCount(long accountId, boolean writable) {
        if (!writable) {
            return 0;
        }
        return jdbc.sql(TODO_CANDIDATES + " select count(*) from candidate")
                .param("account", accountId).param("writable", true)
                .query(Long.class).single();
    }

    /**
     * Buyers of a product whose request or trade is still active. Ended requests and terminal
     * trades are excluded by the status predicate, so an edit cannot notify an unrelated buyer.
     */
    public List<ProductNoticeTarget> productNoticeTargets(long productId) {
        return jdbc.sql("""
                        select t.id as trade_id, t.buyer_id,
                               coalesce(s.title, case
                                   when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                                   then p.title end) as product_title
                          from trade t
                          left join trade_item_snapshot s on s.trade_id = t.id
                          left join product p on p.product_id = t.product_id
                         where t.product_id = :product
                           and t.status in ('pending_acceptance', 'in_progress', 'disputed', 'abnormal')
                         order by t.id
                        """)
                .param("product", productId)
                .query((row, index) -> new ProductNoticeTarget(row.getLong("trade_id"), row.getLong("buyer_id"),
                        row.getString("product_title")))
                .list();
    }

    /** Title and note for a recipient's source projection; empty when the reader is not a participant. */
    public Optional<ProductNoticeContext> productNoticeContext(long tradeId, long viewerId) {
        return jdbc.sql("""
                        select coalesce(s.title, case
                                   when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                                   then p.title end) as product_title, t.request_note
                          from trade t
                          left join trade_item_snapshot s on s.trade_id = t.id
                          left join product p on p.product_id = t.product_id
                         where t.id = :trade
                           and (t.buyer_id = :viewer or t.seller_id = :viewer)
                        """)
                .param("trade", tradeId).param("viewer", viewerId)
                .query((row, index) -> new ProductNoticeContext(row.getString("product_title"),
                        row.getString("request_note")))
                .optional();
    }

    public record PurchaseProductSnapshot(int contentVersion, String title, String description,
                                          long priceCents, Instant capturedAt) {}

    public Optional<PurchaseProductSnapshot> buyerPurchaseProduct(long productId, long buyerId, long tradeId) {
        return jdbc.sql("""
                        select s.content_version, s.title, s.description, s.price_cents, s.captured_at
                          from trade_purchase_product_snapshot s
                          join trade t on t.id = s.trade_id
                         where t.id = :trade and t.product_id = :product and t.buyer_id = :buyer
                        """).param("trade", tradeId).param("product", productId).param("buyer", buyerId)
                .query((row, index) -> new PurchaseProductSnapshot(row.getInt("content_version"),
                        row.getString("title"), row.getString("description"), row.getLong("price_cents"),
                        row.getTimestamp("captured_at").toInstant())).optional();
    }

    /**
     * Start of the product-edit range a buyer may read.
     *
     * <p>With {@code tradeId} the trade must be this buyer's request for this product. Without it
     * the earliest matching request defines the scope, which is explicit and stable. Any other
     * caller gets an empty result so the product API can answer 404.
     */
    public Optional<Instant> buyerHistoryStart(long productId, long buyerId, Long tradeId) {
        if (tradeId == null) {
            return jdbc.sql("""
                            select min(requested_at) as requested_at
                              from trade
                             where product_id = :product and buyer_id = :buyer
                            """)
                    .param("product", productId).param("buyer", buyerId)
                    .query((row, index) -> instant(row, "requested_at"))
                    .optional();
        }
        return jdbc.sql("""
                        select requested_at
                          from trade
                         where id = :trade and product_id = :product and buyer_id = :buyer
                        """)
                .param("trade", tradeId).param("product", productId).param("buyer", buyerId)
                .query((row, index) -> instant(row, "requested_at"))
                .optional();
    }

    private record StatusCount(String status, long total, long buying, long selling) {
    }

    private record KindCount(String kind, long total) {
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    private static Long nullableLong(ResultSet row, String column) throws SQLException {
        long value = row.getLong(column);
        return row.wasNull() ? null : value;
    }

    /**
     * Four current kinds share this candidate query. The predicates mirror the current action
     * eligibility: seller for a pending request, counterpart for a pending agreement or
     * cancellation, and a current counterpart confirmation for completion. An active freeze
     * removes every trade action.
     */
    private static final String TODO_CANDIDATE_SELECT = """
                select 'request_response'::text as kind, t.id as source_id, t.id as trade_id,
                       null::bigint as agreement_id, null::bigint as confirmation_id,
                       null::bigint as cancellation_id, t.requested_at as created_at,
                       t.requested_at as updated_at, t.product_id,
                       coalesce(s.title, case
                           when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                           then p.title end) as title,
                       null::bigint as case_id, null::text as inquiry_action_ids
                  from trade t
                  left join trade_item_snapshot s on s.trade_id = t.id
                  left join product p on p.product_id = t.product_id
                 where :writable and t.status = 'pending_acceptance' and t.seller_id = :account
                   and p.deleted_at is null and p.lifecycle_state = 'public'
                   and p.occupied_by_trade_id is null
                   and not exists (select 1 from trade_freeze f
                                    where f.trade_id = t.id and f.ended_at is null)
                union all
                select 'agreement_response', a.id, t.id, a.id, null, null,
                       a.proposed_at, a.proposed_at, t.product_id,
                       coalesce(s.title, case
                           when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                           then p.title end),
                       null, null
                  from trade t
                  join agreement_version a on a.trade_id = t.id and a.status = 'proposed'
                  left join trade_item_snapshot s on s.trade_id = t.id
                  left join product p on p.product_id = t.product_id
                 where :writable and t.status = 'in_progress'
                   and (t.buyer_id = :account or t.seller_id = :account)
                   and a.proposed_by <> :account
                   and not exists (select 1 from trade_freeze f
                                    where f.trade_id = t.id and f.ended_at is null)
                union all
                select 'completion_response', c.id, t.id, c.agreement_id, c.id, null,
                       c.submitted_at, c.submitted_at, t.product_id,
                       coalesce(s.title, case
                           when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                           then p.title end),
                       null, null
                  from trade t
                  join trade_confirmation c on c.trade_id = t.id and c.invalidated_at is null
                  left join trade_item_snapshot s on s.trade_id = t.id
                  left join product p on p.product_id = t.product_id
                 where :writable and t.status = 'in_progress'
                   and t.active_agreement_id = c.agreement_id
                   and (t.buyer_id = :account or t.seller_id = :account)
                   and c.confirmer_id <> :account
                   and not exists (select 1 from trade_confirmation own
                                    where own.trade_id = t.id and own.confirmer_id = :account
                                      and own.invalidated_at is null)
                   and not exists (select 1 from trade_freeze f
                                    where f.trade_id = t.id and f.ended_at is null)
                union all
                select 'cancellation_response', cp.id, t.id, null, null, cp.id,
                       cp.proposed_at, cp.proposed_at, t.product_id,
                       coalesce(s.title, case
                           when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                           then p.title end),
                       null, null
                  from trade t
                  join cancellation_proposal cp on cp.trade_id = t.id and cp.status = 'pending'
                  left join trade_item_snapshot s on s.trade_id = t.id
                  left join product p on p.product_id = t.product_id
                 where :writable and t.status in ('in_progress', 'disputed')
                   and (t.buyer_id = :account or t.seller_id = :account)
                   and cp.proposed_by <> :account
                   and not exists (select 1 from trade_freeze f
                                    where f.trade_id = t.id and f.ended_at is null)
            """;

    private static final String TODO_CANDIDATES = "with candidate as (" + TODO_CANDIDATE_SELECT + ") ";

    /**
     * Trade-owned candidate projection reused by the account-level mixed todo union.
     * The columns match the case-owned projection and keep the exact predicates of
     * {@link #todos}.
     */
    public static String todoCandidateSql() {
        return TODO_CANDIDATE_SELECT;
    }
}
