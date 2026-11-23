package io.github.iy88.project1.casemanagement.persistence;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CaseCommands;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Case-owned persistence for the report/dispute/exception lifecycle. The product-review rows keep
 * their own entity mapping; lifecycle columns and append-only facts are read and written here in
 * the caller's transaction. Column sets are built from non-null values so PostgreSQL never has to
 * infer the type of an untyped null parameter.
 */
@Service
@Profile("infrastructure")
public class CaseLifecycleStore {
    private static final String FACTS = """
            select id, case_type, target_type, target_id, target_conversation_kind, target_conversation_id,
                   reporter_account_id, reported_reason, claimed_manager_id, claimed_at, case_status,
                   decision_kind, reason_text, decided_by, decided_at, archived_at, public_summary,
                   public_reason, public_result_at, created_at, updated_at
            from moderation_case
            """;

    private static final String ACTIONS = """
            select id, case_id, action_kind, actor_kind, actor_account_id, occurred_at, message_id,
                   related_account_id, inquiry_action_id, appeal_action_id, resolution, note, basis_ref
            from moderation_case_action
            """;

    private final JdbcClient jdbc;

    public CaseLifecycleStore(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public static LockPlan.Key lockKey(long caseId) {
        if (caseId <= 0) {
            throw new IllegalArgumentException("Invalid case id");
        }
        return new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId));
    }

    public long openReport(CaseCommands.Target target, long reporterAccountId, String reason, Instant at) {
        var values = new LinkedHashMap<String, Object>();
        values.put("case_type", CaseVocabulary.REPORT);
        values.put("created_at", stamp(at));
        values.put("updated_at", stamp(at));
        values.put("target_type", target.targetType());
        values.put("target_id", target.targetId());
        if (target.conversationKind() != null) {
            values.put("target_conversation_kind", target.conversationKind());
            values.put("target_conversation_id", target.conversationId());
        }
        values.put("reporter_account_id", reporterAccountId);
        values.put("reported_reason", reason);
        values.put("case_status", CaseVocabulary.PENDING);
        return insert("moderation_case", values, "id");
    }

    /** Opens the exception case created by a trade timeout. The case enters the shared pool. */
    public long openTradeCase(String caseType, long tradeId, Instant at) {
        var values = new LinkedHashMap<String, Object>();
        values.put("case_type", caseType);
        values.put("created_at", stamp(at));
        values.put("updated_at", stamp(at));
        values.put("target_type", "trade");
        values.put("target_id", tradeId);
        values.put("case_status", CaseVocabulary.PENDING);
        return insert("moderation_case", values, "id");
    }

    /**
     * Opens a report unless the same reporter already has an open report for the object. The
     * partial unique index arbitrates concurrent submissions without aborting the transaction.
     */
    public Optional<Long> openReportIfAbsent(CaseCommands.Target target, long reporterAccountId, String reason,
                                             Instant at) {
        if ("message".equals(target.targetType())) {
            return jdbc.sql("""
                            insert into moderation_case (case_type, created_at, updated_at, target_type,
                                target_id, target_conversation_kind, target_conversation_id,
                                reporter_account_id, reported_reason, case_status)
                            values ('report', ?, ?, 'message', ?, ?, ?, ?, ?, 'pending')
                            on conflict (reporter_account_id, target_conversation_kind, target_id)
                                where archived_at is null and case_type = 'report' and target_type = 'message'
                            do nothing
                            returning id
                            """)
                    .param(stamp(at)).param(stamp(at)).param(target.targetId())
                    .param(target.conversationKind()).param(target.conversationId())
                    .param(reporterAccountId).param(reason)
                    .query(Long.class).optional();
        }
        return jdbc.sql("""
                        insert into moderation_case (case_type, created_at, updated_at, target_type,
                            target_id, reporter_account_id, reported_reason, case_status)
                        values ('report', ?, ?, ?, ?, ?, ?, 'pending')
                        on conflict (reporter_account_id, target_type, target_id)
                            where archived_at is null and case_type = 'report' and target_type <> 'message'
                        do nothing
                        returning id
                        """)
                .param(stamp(at)).param(stamp(at)).param(target.targetType()).param(target.targetId())
                .param(reporterAccountId).param(reason)
                .query(Long.class).optional();
    }

    public Optional<CaseRecords.Facts> find(long caseId) {
        return jdbc.sql(FACTS + " where id = ?").param(caseId).query(this::facts).optional();
    }

    /**
     * Locks the case row without declaring a new lock-plan key. Callers already running inside a
     * planned case lock (their own or the trade governance path) use this to re-read the row.
     */
    public CaseRecords.Facts requireLocked(WriteTransaction transaction, long caseId) {
        return jdbc.sql(FACTS + " where id = ? for update").param(caseId).query(this::facts)
                .optional().orElseThrow(CaseLifecycleStore::notVisible);
    }

    public CaseRecords.Facts require(long caseId) {
        return find(caseId).orElseThrow(CaseLifecycleStore::notVisible);
    }

    /** Locks the case row in the caller's transaction and returns the current facts. */
    public CaseRecords.Facts lock(WriteTransaction transaction, long caseId) {
        var holder = new AtomicReference<CaseRecords.Facts>();
        transaction.lock(lockKey(caseId), () -> holder.set(jdbc.sql(FACTS + " where id = ? for update")
                .param(caseId).query(this::facts).optional().orElseThrow(CaseLifecycleStore::notVisible)));
        if (holder.get() == null) {
            throw notVisible();
        }
        return holder.get();
    }

    public Optional<CaseRecords.Facts> findOpenReport(long reporterAccountId, CaseCommands.Target target) {
        String sql = FACTS + " where case_type = 'report' and archived_at is null"
                + " and reporter_account_id = ? and target_type = ? and target_id = ?"
                + ("message".equals(target.targetType())
                ? " and target_conversation_kind = ?" : "");
        var spec = jdbc.sql(sql).param(reporterAccountId).param(target.targetType()).param(target.targetId());
        if ("message".equals(target.targetType())) {
            spec = spec.param(target.conversationKind());
        }
        return spec.query(this::facts).optional();
    }

    /** A closed report by the same reporter blocks a new submission for the same object. */
    public Optional<CaseRecords.Facts> findClosedReport(long reporterAccountId, CaseCommands.Target target) {
        String sql = FACTS + " where case_type = 'report' and archived_at is not null"
                + " and reporter_account_id = ? and target_type = ? and target_id = ?"
                + ("message".equals(target.targetType())
                ? " and target_conversation_kind = ?" : "")
                + " order by id desc limit 1";
        var spec = jdbc.sql(sql).param(reporterAccountId).param(target.targetType()).param(target.targetId());
        if ("message".equals(target.targetType())) {
            spec = spec.param(target.conversationKind());
        }
        return spec.query(this::facts).optional();
    }

    /** Claims the case when still pending; a concurrent claimant serializes on the row lock. */
    public CaseRecords.Facts claim(long caseId, long managerId, Instant at) {
        int updated = jdbc.sql("""
                        update moderation_case
                           set claimed_manager_id = ?, claimed_at = ?, case_status = 'claimed', updated_at = ?
                         where id = ? and case_status = 'pending' and claimed_manager_id is null
                        """)
                .param(managerId).param(stamp(at)).param(stamp(at)).param(caseId).update();
        var current = require(caseId);
        if (updated == 0) {
            if (current.claimedBy(managerId)) {
                return current;
            }
            throw new BusinessError("CASE_ALREADY_CLAIMED", 409, "事项已被其他管理员认领");
        }
        return current;
    }

    public CaseRecords.Facts decide(long caseId, String decisionKind, String reason, long managerId, Instant at) {
        jdbc.sql("""
                        update moderation_case
                           set case_status = 'decided', decision_kind = ?, reason_text = ?, decided_by = ?,
                               decided_at = ?, updated_at = ?
                         where id = ?
                        """)
                .param(decisionKind).param(reason).param(managerId).param(stamp(at)).param(stamp(at))
                .param(caseId).update();
        return require(caseId);
    }

    /**
     * Decision write used when the same transaction also takes subject locks. The conditional
     * update serializes two managers deciding the same case even without an explicit case lock.
     */
    public boolean decideIfClaimed(long caseId, String decisionKind, String reason, long managerId, Instant at) {
        return jdbc.sql("""
                        update moderation_case
                           set case_status = 'decided', decision_kind = ?, reason_text = ?, decided_by = ?,
                               decided_at = ?, updated_at = ?
                         where id = ? and case_status = 'claimed' and claimed_manager_id = ?
                           and archived_at is null
                        """)
                .param(decisionKind).param(reason).param(managerId).param(stamp(at)).param(stamp(at))
                .param(caseId).param(managerId).update() == 1;
    }

    public CaseRecords.Facts archive(long caseId, Instant at) {
        jdbc.sql("update moderation_case set archived_at = ?, updated_at = ? where id = ? and archived_at is null")
                .param(stamp(at)).param(stamp(at)).param(caseId).update();
        return require(caseId);
    }

    public CaseRecords.Facts publish(long caseId, String summary, String reason, long managerId, Instant at) {
        jdbc.sql("""
                        update moderation_case
                           set public_summary = ?, public_reason = ?, public_result_at = ?, published_by = ?,
                               updated_at = ?
                         where id = ? and public_result_at is null
                        """)
                .param(summary).param(reason).param(stamp(at)).param(managerId).param(stamp(at))
                .param(caseId).update();
        return require(caseId);
    }

    public void touch(long caseId, Instant at) {
        jdbc.sql("update moderation_case set updated_at = ? where id = ?").param(stamp(at)).param(caseId).update();
    }

    public long addAction(CaseRecords.Action action) {
        var values = new LinkedHashMap<String, Object>();
        values.put("case_id", action.caseId());
        values.put("action_kind", action.actionKind());
        values.put("actor_kind", action.actorKind());
        if (action.actorAccountId() != null) {
            values.put("actor_account_id", action.actorAccountId());
        }
        values.put("occurred_at", stamp(action.occurredAt()));
        if (action.messageId() != null) {
            values.put("message_id", action.messageId());
        }
        if (action.relatedAccountId() != null) {
            values.put("related_account_id", action.relatedAccountId());
        }
        if (action.inquiryActionId() != null) {
            values.put("inquiry_action_id", action.inquiryActionId());
        }
        if (action.appealActionId() != null) {
            values.put("appeal_action_id", action.appealActionId());
        }
        if (action.resolution() != null) {
            values.put("resolution", action.resolution());
        }
        if (action.note() != null) {
            values.put("note", action.note());
        }
        if (action.basisRef() != null) {
            values.put("basis_ref", action.basisRef());
        }
        return insert("moderation_case_action", values, "id", "basis_ref");
    }

    public List<CaseRecords.Action> actions(long caseId) {
        return jdbc.sql(ACTIONS + " where case_id = ? order by id").param(caseId).query(this::action).list();
    }

    public Optional<CaseRecords.Action> action(long caseId, long actionId) {
        return jdbc.sql(ACTIONS + " where case_id = ? and id = ?").param(caseId).param(actionId)
                .query(this::action).optional();
    }

    public Optional<CaseRecords.Action> appealOf(long caseId, long accountId) {
        return jdbc.sql(ACTIONS + " where case_id = ? and action_kind = 'appeal' and actor_account_id = ?"
                        + " order by id limit 1")
                .param(caseId).param(accountId).query(this::action).optional();
    }

    public Optional<CaseRecords.Action> latestPendingAppeal(long caseId) {
        return jdbc.sql(ACTIONS + " where case_id = ? and action_kind = 'appeal' and not exists ("
                        + " select 1 from moderation_case_action r where r.case_id = moderation_case_action.case_id"
                        + " and r.action_kind = 'manager_reply' and r.appeal_action_id = moderation_case_action.id)"
                        + " order by id limit 1")
                .param(caseId).query(this::action).optional();
    }

    public boolean statementExists(long caseId, long inquiryActionId) {
        return count("select count(*) from moderation_case_action where case_id = ?"
                + " and action_kind = 'statement' and inquiry_action_id = ?", caseId, inquiryActionId) > 0;
    }

    public boolean appealResolved(long caseId, long appealActionId) {
        return count("select count(*) from moderation_case_action where case_id = ?"
                + " and action_kind = 'manager_reply' and appeal_action_id = ?", caseId, appealActionId) > 0;
    }

    public long addEvidence(long caseId, long fileId, Long referenceId, long submittedBy, Instant at) {
        var values = new LinkedHashMap<String, Object>();
        values.put("case_id", caseId);
        values.put("evidence_kind", "submitter_attachment");
        values.put("file_id", fileId);
        if (referenceId != null) {
            values.put("file_reference_id", referenceId);
        }
        values.put("submitted_by", submittedBy);
        values.put("submitted_at", stamp(at));
        return insert("case_evidence", values, "id");
    }

    public List<CaseRecords.Evidence> evidence(long caseId) {
        return jdbc.sql("""
                        select id, case_id, evidence_kind, file_id, file_reference_id, source_ref_type,
                               source_ref_id, required_scope, submitted_by, submitted_at
                        from case_evidence where case_id = ? order by id
                        """)
                .param(caseId).query((rs, row) -> new CaseRecords.Evidence(rs.getLong("id"),
                        rs.getLong("case_id"), rs.getString("evidence_kind"),
                        rs.getObject("file_id", Long.class), rs.getObject("file_reference_id", Long.class),
                        rs.getString("source_ref_type"), rs.getObject("source_ref_id", Long.class),
                        rs.getString("required_scope"), rs.getObject("submitted_by", Long.class),
                        instant(rs, "submitted_at"))).list();
    }

    public void addAppealEligibility(long caseId, long accountId, Instant deadline, String basisRef, Instant at) {
        var values = new LinkedHashMap<String, Object>();
        values.put("case_id", caseId);
        values.put("account_id", accountId);
        values.put("appeal_deadline_at", stamp(deadline));
        if (basisRef != null) {
            values.put("basis_ref", basisRef);
        }
        values.put("created_at", stamp(at));
        insert("case_appeal_eligibility", values, "id");
    }

    public Optional<CaseRecords.AppealEligibility> appealEligibility(long caseId, long accountId) {
        return jdbc.sql("select case_id, account_id, appeal_deadline_at, basis_ref from case_appeal_eligibility"
                        + " where case_id = ? and account_id = ?")
                .param(caseId).param(accountId)
                .query((rs, row) -> new CaseRecords.AppealEligibility(rs.getLong("case_id"),
                        rs.getLong("account_id"), instant(rs, "appeal_deadline_at"), rs.getString("basis_ref")))
                .optional();
    }

    public List<CaseRecords.AppealEligibility> appealEligibilities(long caseId) {
        return jdbc.sql("select case_id, account_id, appeal_deadline_at, basis_ref from case_appeal_eligibility"
                        + " where case_id = ? order by account_id")
                .param(caseId)
                .query((rs, row) -> new CaseRecords.AppealEligibility(rs.getLong("case_id"),
                        rs.getLong("account_id"), instant(rs, "appeal_deadline_at"), rs.getString("basis_ref")))
                .list();
    }

    public void addEnforcement(CaseRecords.Enforcement enforcement) {
        var values = new LinkedHashMap<String, Object>();
        values.put("case_id", enforcement.caseId());
        values.put("enforcement_id", enforcement.enforcementId());
        values.put("action", enforcement.action());
        values.put("target_type", enforcement.targetType());
        values.put("target_id", enforcement.targetId());
        if (enforcement.basisRef() != null) {
            values.put("basis_ref", enforcement.basisRef());
        }
        values.put("requested_by", enforcement.requestedBy());
        values.put("requested_at", stamp(enforcement.requestedAt()));
        if (enforcement.resultType() != null) {
            values.put("result_type", enforcement.resultType());
            values.put("result_id", enforcement.resultId());
        }
        values.put("result_status", enforcement.resultStatus());
        if (enforcement.previousState() != null) {
            values.put("previous_state", enforcement.previousState());
        }
        if (enforcement.currentState() != null) {
            values.put("current_state", enforcement.currentState());
        }
        values.put("affected_scope", affectedScope(enforcement));
        values.put("occurred_at", stamp(enforcement.occurredAt()));
        insert("case_enforcement", values, "id", "affected_scope");
    }

    /** Minimal JSONB projection of the actually affected accounts. */
    private static String affectedScope(CaseRecords.Enforcement enforcement) {
        return enforcement.affectedAccountIds().stream()
                .map(id -> "{\"resource_type\":\"account\",\"resource_id\":\"" + id + "\"}")
                .collect(Collectors.joining(",", "[", "]"));
    }

    public List<CaseRecords.Enforcement> enforcements(long caseId) {
        return jdbc.sql("""
                        select id, case_id, enforcement_id, action, target_type, target_id, basis_ref,
                               requested_by, requested_at, result_type, result_id, result_status,
                               previous_state, current_state, affected_scope::text as affected_scope,
                               failure_code, failure_reason, occurred_at
                        from case_enforcement where case_id = ? order by id
                        """)
                .param(caseId).query(this::enforcement).list();
    }

    public Optional<CaseRecords.Enforcement> enforcement(long caseId, String enforcementId) {
        return jdbc.sql("""
                        select id, case_id, enforcement_id, action, target_type, target_id, basis_ref,
                               requested_by, requested_at, result_type, result_id, result_status,
                               previous_state, current_state, affected_scope::text as affected_scope,
                               failure_code, failure_reason, occurred_at
                        from case_enforcement where case_id = ? and enforcement_id = ?
                        """)
                .param(caseId).param(enforcementId).query(this::enforcement).optional();
    }

    /** Distinct related accounts that hold a thread or an appeal for this case. */
    public List<Long> relatedAccountIds(long caseId) {
        return jdbc.sql("""
                        select related_account_id from (
                            select distinct related_account_id
                              from moderation_case_action
                             where case_id = ? and related_account_id is not null
                            union
                            select account_id from case_appeal_eligibility where case_id = ?
                        ) accounts order by related_account_id
                        """)
                .param(caseId).param(caseId).query(Long.class).list();
    }

    public boolean exists(long caseId) {
        return count("select count(*) from moderation_case where id = ?", caseId) > 0;
    }

    public boolean claimedByManager(long caseId, long managerId) {
        return count("select count(*) from moderation_case where id = ? and claimed_manager_id = ?",
                caseId, managerId) > 0;
    }

    private long insert(String table, Map<String, Object> values, String returning, String... jsonColumns) {
        var json = java.util.Set.of(jsonColumns);
        String columns = String.join(", ", values.keySet());
        String marks = values.keySet().stream()
                .map(column -> json.contains(column) ? "?::jsonb" : "?")
                .collect(Collectors.joining(", "));
        return jdbc.sql("insert into " + table + " (" + columns + ") values (" + marks + ") returning " + returning)
                .params(values.values().toArray()).query(Long.class).single();
    }

    private long count(String sql, Object... values) {
        return jdbc.sql(sql).params(values).query(Long.class).single();
    }

    private CaseRecords.Facts facts(ResultSet rs, int row) throws SQLException {
        return new CaseRecords.Facts(rs.getLong("id"), rs.getString("case_type"), rs.getString("target_type"),
                rs.getObject("target_id", Long.class), rs.getString("target_conversation_kind"),
                rs.getObject("target_conversation_id", Long.class), rs.getObject("reporter_account_id", Long.class),
                rs.getString("reported_reason"), rs.getObject("claimed_manager_id", Long.class),
                instant(rs, "claimed_at"), rs.getString("case_status"), rs.getString("decision_kind"),
                rs.getString("reason_text"), rs.getObject("decided_by", Long.class), instant(rs, "decided_at"),
                instant(rs, "archived_at"), rs.getString("public_summary"), rs.getString("public_reason"),
                instant(rs, "public_result_at"), instant(rs, "created_at"), instant(rs, "updated_at"));
    }

    private CaseRecords.Action action(ResultSet rs, int row) throws SQLException {
        return new CaseRecords.Action(rs.getLong("id"), rs.getLong("case_id"), rs.getString("action_kind"),
                rs.getString("actor_kind"), rs.getObject("actor_account_id", Long.class),
                instant(rs, "occurred_at"), rs.getObject("message_id", Long.class),
                rs.getObject("related_account_id", Long.class), rs.getObject("inquiry_action_id", Long.class),
                rs.getObject("appeal_action_id", Long.class), rs.getString("resolution"), rs.getString("note"),
                rs.getString("basis_ref"));
    }

    private CaseRecords.Enforcement enforcement(ResultSet rs, int row) throws SQLException {
        return new CaseRecords.Enforcement(rs.getString("enforcement_id"), rs.getLong("case_id"),
                rs.getString("action"), rs.getString("target_type"), rs.getLong("target_id"),
                rs.getString("basis_ref"), rs.getLong("requested_by"), instant(rs, "requested_at"),
                rs.getString("result_type"), rs.getObject("result_id", Long.class), rs.getString("result_status"),
                rs.getString("previous_state"), rs.getString("current_state"),
                affectedAccounts(rs.getString("affected_scope")), rs.getString("failure_code"),
                rs.getString("failure_reason"), instant(rs, "occurred_at"));
    }

    private static List<Long> affectedAccounts(String scope) {
        if (scope == null || scope.isBlank()) {
            return List.of();
        }
        var matcher = java.util.regex.Pattern.compile("\\\"resource_id\\\":\\\"(\\d+)\\\"").matcher(scope);
        var ids = new java.util.ArrayList<Long>();
        while (matcher.find()) {
            ids.add(Long.parseLong(matcher.group(1)));
        }
        return ids;
    }

    private static OffsetDateTime stamp(Instant at) {
        return at.atOffset(ZoneOffset.UTC);
    }

    private static Instant instant(ResultSet rs, String column) throws SQLException {
        OffsetDateTime value = rs.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
    }
}
