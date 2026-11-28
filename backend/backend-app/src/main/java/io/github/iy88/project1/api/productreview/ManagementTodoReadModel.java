package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.casemanagement.application.TodoItem;
import io.github.iy88.project1.casemanagement.application.TodoKinds;
import io.github.iy88.project1.casemanagement.application.TodoOwnership;
import io.github.iy88.project1.casemanagement.application.TodoPage;
import io.github.iy88.project1.casemanagement.application.TodoQuery;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** Combines review and lifecycle facts in the read-only snapshot opened by the query application. */
@Component
@Profile("infrastructure")
class ManagementTodoReadModel {
    private static final String REVIEW_ROWS = """
            select c.id, c.case_type, c.created_at,
                   greatest(c.created_at, c.claimed_at, a.decided_at) as updated_at,
                   case a.status when 'passed' then 'approved' when 'rejected' then 'rejected' end as decision_kind,
                   coalesce(a.decided_by_admin_id, c.claimed_manager_id) as manager_id,
                   a.decided_at as completed_at,
                   case when a.status = 'pending' then p.title
                        else coalesce(a.reviewed_content ->> 'title', '商品审核') end as title,
                   a.audit_id, a.product_id
            from moderation_case c
            join product_audit a on a.case_id = c.id
            join product p on p.product_id = a.product_id
            where c.case_type = 'product_review'
              and ((a.status = 'pending' and p.lifecycle_state = 'pending_review' and p.deleted_at is null)
                or (a.status in ('passed', 'rejected') and a.decided_at is not null))
            """;

    private static final String LIFECYCLE_ROWS = """
            select c.id, c.case_type, c.created_at, c.updated_at, c.decision_kind,
                   coalesce(closed.actor_account_id, c.claimed_manager_id),
                   c.archived_at,
                   case c.case_type
                       when 'dispute' then '交易争议'
                       when 'exception' then '交易异常'
                       when 'report' then case c.target_type
                           when 'product' then '商品举报'
                           when 'comment' then '评论举报'
                           when 'message' then '消息举报'
                           when 'evaluation' then '评价举报'
                           when 'account' then '账户举报'
                           else '举报' end
                   end,
                   null::bigint, null::bigint
            from moderation_case c
            left join moderation_case_action closed on closed.case_id = c.id and closed.action_kind = 'close'
            where c.case_type in ('report', 'dispute', 'exception')
              and (c.archived_at is not null or c.claimed_manager_id is not null or c.case_status = 'pending')
            """;

    private final JdbcClient jdbc;

    ManagementTodoReadModel(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional(readOnly = true, propagation = Propagation.MANDATORY)
    public TodoPage page(TodoQuery query) {
        String source = """
                with candidates as (
                """ + REVIEW_ROWS + " union all " + LIFECYCLE_ROWS + """
                ), visible as (
                    select * from candidates
                    where %s
                      and (:keyword = '' or strpos(id::text, :keyword) > 0
                           or strpos(lower(title), lower(:keyword)) > 0)
                )
                """.formatted(scope(query.ownership()));
        Map<String, Long> counts = new LinkedHashMap<>();
        statement(source + "select case_type, count(*) from visible group by case_type", query)
                .query((row, index) -> Map.entry(row.getString("case_type"), row.getLong(2)))
                .list().forEach(row -> counts.put(row.getKey(), row.getValue()));
        boolean all = TodoKinds.ALL_KINDS.equals(query.kind());
        long total = all ? counts.values().stream().mapToLong(element -> element.longValue()).sum()
                : counts.getOrDefault(query.kind(), 0L);
        String order = switch (query.ownership()) {
            case UNCLAIMED, MINE -> "updated_at";
            case COMPLETED_ALL, COMPLETED_MINE -> "completed_at";
        };
        var rows = statement(source + """
                select * from visible where (:kind = 'all' or case_type = :kind)
                order by
                """ + order + " desc, id desc limit :limit offset :offset", query)
                .param("kind", query.kind())
                .param("limit", query.pageSize())
                .param("offset", (long) (query.page() - 1) * query.pageSize())
                .query(ManagementTodoReadModel::item).list();
        var asOf = jdbc.sql("select transaction_timestamp()").query(OffsetDateTime.class).single().toInstant();
        return new TodoPage(rows, total, counts, asOf);
    }

    private JdbcClient.StatementSpec statement(String sql, TodoQuery query) {
        var statement = jdbc.sql(sql).param("keyword", query.keyword());
        return switch (query.ownership()) {
            case MINE, COMPLETED_MINE -> statement.param("manager", query.managerId());
            case UNCLAIMED, COMPLETED_ALL -> statement;
        };
    }

    private static String scope(TodoOwnership ownership) {
        return switch (ownership) {
            case UNCLAIMED -> "completed_at is null and manager_id is null";
            case MINE -> "completed_at is null and manager_id = :manager";
            case COMPLETED_ALL -> "completed_at is not null";
            case COMPLETED_MINE -> "completed_at is not null and manager_id = :manager";
        };
    }

    private static TodoItem item(ResultSet row, int index) throws SQLException {
        return new TodoItem(row.getLong("id"), row.getString("case_type"),
                instant(row, "created_at"), instant(row, "updated_at"), row.getString("decision_kind"),
                row.getObject("manager_id", Long.class), instant(row, "completed_at"), row.getString("title"),
                row.getObject("audit_id", Long.class), row.getObject("product_id", Long.class));
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        var timestamp = row.getObject(column, OffsetDateTime.class);
        return timestamp == null ? null : timestamp.toInstant();
    }
}
