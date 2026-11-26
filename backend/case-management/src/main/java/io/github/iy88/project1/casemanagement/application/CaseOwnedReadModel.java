package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Case-owned read projections for the account aggregation (API-COM-QUERY-001/002/003).
 *
 * <p>It reads the lifecycle facts only: reports the account submitted, reports whose
 * executions actually affected the account, and one inquiry todo per open case with an
 * unanswered inquiry for that account. A report becomes visible in the received direction
 * only through a real enforcement fact or the persisted appeal eligibility created by it;
 * an inquiry alone never qualifies. Query text never includes the reporter identity or the
 * other side's statement.
 */
@Service
@Profile("infrastructure")
public class CaseOwnedReadModel {
    /** Rows of the report resource list. */
    public record ReportRow(long caseId, String direction, String state, Instant updatedAt, String summary) {
    }

    public record ReportPage(List<ReportRow> items, long total) {
        public ReportPage {
            items = List.copyOf(items);
        }
    }

    public record ReportCounts(long submitted, long received) {
    }

    private static final String REPORT_COLUMNS = """
            select c.id as case_id, c.case_status, c.updated_at, c.public_summary,
                   c.public_reason
              from moderation_case c
             where c.case_type = 'report'
            """;

    /** Real executed disposition of this account, or the appeal eligibility it persisted. */
    private static final String RECEIVED_PREDICATE = """
            (c.reporter_account_id is null or c.reporter_account_id <> :account)
            and (
                exists (select 1 from case_appeal_eligibility e
                         where e.case_id = c.id and e.account_id = :account)
                or exists (select 1 from case_enforcement en
                            where en.case_id = c.id
                              and en.result_status in ('applied', 'replayed')
                              and exists (select 1
                                            from jsonb_array_elements(en.affected_scope) scope
                                           where scope ->> 'resource_type' = 'account'
                                             and scope ->> 'resource_id' = :account_text))
            )
            """;

    private static final String RECEIVED_VISIBILITY = " and " + RECEIVED_PREDICATE;

    /**
     * One inquiry todo per case. The thread join keeps the same current-response rule as the
     * write path: an open case, the related account's live thread, the inquiry action and no
     * statement that references that action. Inquiry availability is independent of the
     * ordinary trade write restriction, so a banned account keeps this approved channel.
     */
    private static final String TODO_CANDIDATE_SELECT = """
                select 'inquiry_response'::text as kind, c.id as source_id,
                       null::bigint as trade_id, null::bigint as agreement_id,
                       null::bigint as confirmation_id, null::bigint as cancellation_id,
                       c.created_at as created_at, c.updated_at as updated_at,
                       null::bigint as product_id, null::text as title,
                       c.id as case_id,
                       string_agg(a.id::text, ',' order by a.id) as inquiry_action_ids
                  from moderation_case c
                  join moderation_case_action a
                    on a.case_id = c.id
                   and a.action_kind = 'inquire'
                   and a.related_account_id = :account
                   and a.message_id is not null
                  join case_conversation cc
                    on cc.case_id = c.id
                   and cc.related_account_id = a.related_account_id
                   and cc.archived_at is null
                 where c.case_type <> 'product_review'
                   and c.archived_at is null
                   and (c.reporter_account_id is null or c.reporter_account_id <> a.related_account_id)
                   and not exists (select 1
                                     from moderation_case_action s
                                    where s.case_id = a.case_id
                                      and s.action_kind = 'statement'
                                      and s.inquiry_action_id = a.id)
                 group by c.id, c.created_at, c.updated_at
            """;

    private final JdbcClient jdbc;

    public CaseOwnedReadModel(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public ReportCounts reportCounts(long accountId) {
        return jdbc.sql("""
                        select count(*) filter (where c.reporter_account_id = :account) as submitted,
                               count(*) filter (where """ + RECEIVED_PREDICATE + """
                               ) as received
                          from moderation_case c
                         where c.case_type = 'report'
                        """)
                .param("account", accountId)
                .param("account_text", Long.toString(accountId))
                .query((row, index) -> new ReportCounts(row.getLong("submitted"), row.getLong("received")))
                .single();
    }

    public ReportPage reports(long accountId, String direction, String state, int limit, long offset) {
        boolean received = "received".equals(direction);
        String where = received ? RECEIVED_VISIBILITY : " and c.reporter_account_id = :account\n";
        StringBuilder filter = new StringBuilder(REPORT_COLUMNS).append(where);
        if (state != null) {
            filter.append(" and c.case_status = :state");
        }
        var count = jdbc.sql("select count(*) from (" + filter + ") visible").param("account", accountId);
        if (received) {
            count = count.param("account_text", Long.toString(accountId));
        }
        if (state != null) {
            count = count.param("state", state);
        }
        long total = count.query(Long.class).single();

        var page = jdbc.sql(filter + " order by c.updated_at desc, c.id desc limit :limit offset :offset")
                .param("account", accountId)
                .param("limit", limit)
                .param("offset", offset);
        if (received) {
            page = page.param("account_text", Long.toString(accountId));
        }
        if (state != null) {
            page = page.param("state", state);
        }
        List<ReportRow> items = page.query((row, index) -> new ReportRow(row.getLong("case_id"), direction,
                        row.getString("case_status"), instant(row, "updated_at"), summary(direction, row)))
                .list();
        return new ReportPage(items, total);
    }

    /** Current inquiry todo count, used by the account overview. */
    public long inquiryTodoCount(long accountId) {
        return jdbc.sql("with candidate as (" + TODO_CANDIDATE_SELECT + ") select count(*) from candidate")
                .param("account", accountId)
                .query(Long.class)
                .single();
    }

    /** Case-owned candidate projection reused by the account-level mixed todo union. */
    public static String todoCandidateSql() {
        return TODO_CANDIDATE_SELECT;
    }

    private static String summary(String direction, ResultSet row) throws SQLException {
        String publicSummary = text(row.getString("public_summary"));
        if (publicSummary != null) {
            return publicSummary;
        }
        if ("submitted".equals(direction)) {
            String publicReason = text(row.getString("public_reason"));
            if (publicReason != null) {
                return publicReason;
            }
        }
        return switch (row.getString("case_status")) {
            case CaseVocabulary.DECIDED -> "received".equals(direction)
                    ? "收到的事项已作出处理决定" : "举报事项已作出处理决定";
            case CaseVocabulary.CLAIMED -> "received".equals(direction)
                    ? "收到的事项正在处理" : "举报事项正在处理";
            default -> "received".equals(direction) ? "收到的事项待处理" : "举报事项待处理";
        };
    }

    private static String text(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
