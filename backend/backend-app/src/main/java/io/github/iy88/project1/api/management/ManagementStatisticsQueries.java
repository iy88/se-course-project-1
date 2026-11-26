package io.github.iy88.project1.api.management;

import io.github.iy88.project1.account.application.AccountManagementReadModel;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.persistence.Product;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/** Composes the management counts from the current facts in one PostgreSQL snapshot. */
@Service
@Profile("infrastructure & !dependency-probe & !file-probe")
public class ManagementStatisticsQueries {
    private final JdbcClient jdbc;
    private final AccountManagementReadModel accounts;

    public ManagementStatisticsQueries(JdbcClient jdbc, AccountManagementReadModel accounts) {
        this.jdbc = jdbc;
        this.accounts = accounts;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Statistics statistics(long managerId, String scope, String startAt, String endAt) {
        var asOf = jdbc.sql("select transaction_timestamp()").query(OffsetDateTime.class).single();
        var accountCounts = accounts.counts(managerId, asOf);
        var selection = selection(scope, startAt, endAt);

        Map<String, Long> products = new LinkedHashMap<>();
        for (String state : new String[]{Product.PENDING_REVIEW, Product.REVIEW_REJECTED, Product.PUBLIC,
                Product.IN_TRADE, Product.OFF_SHELF}) {
            products.put(state, 0L);
        }
        jdbc.sql("""
                select lifecycle_state, count(*) as total
                from product where deleted_at is null group by lifecycle_state
                """).query((row, index) -> Map.entry(row.getString("lifecycle_state"), row.getLong("total")))
                .list().forEach(row -> products.put(row.getKey(), row.getValue()));

        var pending = jdbc.sql("""
                select (select count(*)
                        from product_audit a join product p on p.product_id = a.product_id
                        where a.status = 'pending' and p.lifecycle_state = 'pending_review'
                          and p.deleted_at is null) as reviews,
                       (select count(*)
                        from moderation_case c
                        where c.case_type = 'report'
                          and not exists (select 1 from moderation_case_action a
                                          where a.case_id = c.id and a.action_kind = 'close')) as reports
                """).query((row, index) -> new Pending(row.getLong("reviews"), row.getLong("reports"))).single();

        // ended_at is set with the immutable trade completion transition, including an admin decision.
        var tradeCounts = jdbc.sql("""
                select count(*) filter (where status = 'completed') as completed,
                       count(*) filter (where status = 'terminated') as terminated,
                       count(*) filter (where status = 'disputed') as disputed,
                       count(*) filter (where status = 'completed'
                           and (:all or (ended_at >= :start_at and ended_at < :end_at))) as selected
                from trade
                """).param("all", "all".equals(selection.timeScope()))
                .param("start_at", selection.startAt(), java.sql.Types.TIMESTAMP_WITH_TIMEZONE)
                .param("end_at", selection.endAt(), java.sql.Types.TIMESTAMP_WITH_TIMEZONE)
                .query((row, index) -> new TradeCounts(new Trades(row.getLong("completed"),
                        row.getLong("terminated"), row.getLong("disputed")), row.getLong("selected"))).single();

        return new Statistics(asOf.toInstant(), selection, accountCounts, products, pending,
                tradeCounts.current(), tradeCounts.selected());
    }

    private static Selection selection(String scope, String startAt, String endAt) {
        if ("all".equals(scope) && startAt == null && endAt == null) {
            return new Selection(scope, null, null);
        }
        if ("range".equals(scope) && startAt != null && endAt != null) {
            try {
                var start = OffsetDateTime.parse(startAt);
                var end = OffsetDateTime.parse(endAt);
                if (ZoneOffset.UTC.equals(start.getOffset()) && ZoneOffset.UTC.equals(end.getOffset())
                        && start.getYear() > 0 && end.getYear() <= 9999 && start.isBefore(end)) {
                    return new Selection(scope, start, end);
                }
            } catch (DateTimeParseException ignored) {
                // Invalid time values use the same input error as an invalid selection.
            }
        }
        throw new BusinessError("INPUT_INVALID", 422, "请选择全部时间或有效的 UTC 起止时间");
    }

    public record Statistics(Instant asOf, Selection selection, AccountManagementReadModel.Counts accounts,
                             Map<String, Long> productsByState, Pending pending, Trades trades,
                             long completedInSelection) {}

    public record Selection(String timeScope, OffsetDateTime startAt, OffsetDateTime endAt) {}

    public record Pending(long reviews, long reports) {}

    public record Trades(long completed, long terminated, long disputed) {}

    private record TradeCounts(Trades current, long selected) {}
}
