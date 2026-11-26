package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Read-only projection over the trade review facts owned by the evaluation work package.
 *
 * <p>The table is created by that package's migration. When it is absent the query reports the
 * dependency as unavailable instead of returning an empty page that would look like "no reviews".
 */
@Service
@Profile("infrastructure")
public class TradeReviewReadModel {
    public record EvaluationCounts(long written, long received) {
    }

    public record EvaluationRow(long evaluationId, long tradeId, String direction, Instant createdAt,
                                String content) {
    }

    public record EvaluationPage(List<EvaluationRow> items, long total) {
        public EvaluationPage {
            items = List.copyOf(items);
        }
    }

    private static final String WRITTEN = """
            r.reviewer_id = :account
              and ((t.buyer_id = :account and r.reviewee_id = t.seller_id)
                or (t.seller_id = :account and r.reviewee_id = t.buyer_id))
            """;
    private static final String RECEIVED = """
            r.reviewee_id = :account
              and ((t.buyer_id = :account and r.reviewer_id = t.seller_id)
                or (t.seller_id = :account and r.reviewer_id = t.buyer_id))
            """;

    private final JdbcClient jdbc;

    public TradeReviewReadModel(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public EvaluationCounts counts(long accountId) {
        requireAvailable();
        String sql = "select count(*) filter (where " + WRITTEN + ") as written,"
                + " count(*) filter (where " + RECEIVED + ") as received"
                + " from trade_review r join trade t on t.id = r.trade_id";
        return jdbc.sql(sql)
                .param("account", accountId)
                .query((row, index) -> new EvaluationCounts(row.getLong("written"), row.getLong("received")))
                .single();
    }

    public EvaluationPage page(long accountId, String direction, int limit, long offset) {
        requireAvailable();
        String predicate = predicate(direction);
        String from = " from trade_review r join trade t on t.id = r.trade_id where " + predicate;
        List<EvaluationRow> items = jdbc.sql("select r.id as evaluation_id, r.trade_id, r.created_at,"
                        + " r.visible, r.content" + from
                        + " order by r.created_at desc, r.id desc limit :limit offset :offset")
                .param("account", accountId).param("limit", limit).param("offset", offset)
                .query((row, index) -> new EvaluationRow(row.getLong("evaluation_id"), row.getLong("trade_id"),
                        direction, instant(row, "created_at"),
                        row.getBoolean("visible") ? row.getString("content") : null))
                .list();
        long total = jdbc.sql("select count(*)" + from)
                .param("account", accountId)
                .query(Long.class).single();
        return new EvaluationPage(items, total);
    }

    /** A received evaluation is reportable while its content remains visible to the recipient. */
    public Optional<Long> reportableReviewAuthor(long accountId, long reviewId) {
        requireAvailable();
        return jdbc.sql("select r.reviewer_id from trade_review r join trade t on t.id = r.trade_id"
                        + " where r.id = :review and r.visible and " + RECEIVED)
                .param("review", reviewId).param("account", accountId).query(Long.class).optional();
    }

    /** Resolves the author for a previously accepted report, even after moderation. */
    public Optional<Long> reviewAuthor(long reviewId) {
        requireAvailable();
        return jdbc.sql("select reviewer_id from trade_review where id = :review")
                .param("review", reviewId).query(Long.class).optional();
    }

    private static String predicate(String direction) {
        return switch (direction) {
            case "written" -> WRITTEN;
            case "received" -> RECEIVED;
            default -> throw new BusinessError("INPUT_INVALID", 422, "评价方向无效");
        };
    }

    private void requireAvailable() {
        boolean present = jdbc.sql("""
                        select exists (select 1 from information_schema.tables
                                        where table_schema = 'public' and table_name = 'trade_review')
                        """).query(Boolean.class).single();
        if (!present) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "评价查询暂未接入");
        }
    }

    private static Instant instant(java.sql.ResultSet row, String column) throws java.sql.SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
