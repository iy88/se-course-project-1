package io.github.iy88.project1.api.account;

import io.github.iy88.project1.casemanagement.application.CaseOwnedReadModel;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Account-level mixed todo projection (API-COM-QUERY-002).
 *
 * <p>The trade and case modules expose their own candidate SQL. This class unions those
 * projections and applies one LIMIT/OFFSET after the shared ordering, so a page never
 * concatenates two separately paged lists and never truncates a legal offset. Counts are
 * grouped without the kind filter; the total derives from the same counts with the filter.
 */
@Service
@Profile("infrastructure")
public class OwnedTodoQueries {
    public static final List<String> TODO_KINDS = List.of("request_response", "agreement_response",
            "completion_response", "cancellation_response", "inquiry_response");

    private static final String CANDIDATES = "with candidate as ("
            + TradeOwnedReadModel.todoCandidateSql()
            + " union all "
            + CaseOwnedReadModel.todoCandidateSql()
            + ") ";

    public record Candidate(String kind, long sourceId, Long tradeId, Long agreementId, Long confirmationId,
                            Long cancellationId, Long caseId, String inquiryActionIds, Instant createdAt,
                            Instant updatedAt, Long productId, String title) {
    }

    public record Page(List<Candidate> items, long total, Map<String, Long> countsByKind) {
        public Page {
            items = List.copyOf(items);
            countsByKind = Map.copyOf(countsByKind);
        }
    }

    private final JdbcClient jdbc;

    public OwnedTodoQueries(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Page todos(long accountId, String kind, boolean writable, int limit, long offset) {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String candidate : TODO_KINDS) {
            counts.put(candidate, 0L);
        }
        jdbc.sql(CANDIDATES + "select kind, count(*) as total from candidate group by kind")
                .param("account", accountId)
                .param("writable", writable)
                .query((row, index) -> new KindCount(row.getString("kind"), row.getLong("total")))
                .list()
                .forEach(row -> counts.put(row.kind(), row.total()));

        String filter = kind == null ? "" : " where kind = :kind";
        var page = jdbc.sql(CANDIDATES + "select * from candidate" + filter
                        + " order by updated_at desc, kind asc, source_id desc limit :limit offset :offset")
                .param("account", accountId)
                .param("writable", writable)
                .param("limit", limit)
                .param("offset", offset);
        if (kind != null) {
            page = page.param("kind", kind);
        }
        List<Candidate> items = page.query((row, index) -> new Candidate(row.getString("kind"),
                        row.getLong("source_id"), nullableLong(row, "trade_id"),
                        nullableLong(row, "agreement_id"), nullableLong(row, "confirmation_id"),
                        nullableLong(row, "cancellation_id"), nullableLong(row, "case_id"),
                        row.getString("inquiry_action_ids"), instant(row, "created_at"),
                        instant(row, "updated_at"), nullableLong(row, "product_id"), row.getString("title")))
                .list();
        long total = kind == null
                ? counts.values().stream().mapToLong(entry -> entry.longValue()).sum()
                : counts.getOrDefault(kind, 0L);
        return new Page(items, total, counts);
    }

    private record KindCount(String kind, long total) {
    }

    private static Long nullableLong(ResultSet row, String column) throws SQLException {
        long value = row.getLong(column);
        return row.wasNull() ? null : value;
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
