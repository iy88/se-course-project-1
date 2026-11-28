package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseSettings;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.OptionalLong;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Read side of the case lifecycle: personal lists, the viewpoint-trimmed detail projection and the
 * anonymous public results. Detail fields are computed from the caller's viewpoint; the query never
 * widens access after publication.
 */
public class CaseQueries {
    private final JdbcClient jdbc;
    private final CaseLifecycleStore store;
    private final CasePorts.Threads threads;
    private final CasePorts.Managers managers;
    private final CasePorts.Targets targets;
    private final CasePorts.EvidenceFiles files;
    private final CaseSettings settings;
    private final Clock clock;
    private final JsonMapper json;
    private final CaseDetailQueries detailQueries;

    public CaseQueries(JdbcClient jdbc, CaseLifecycleStore store, CasePorts.Threads threads,
                       CasePorts.Managers managers, CasePorts.Targets targets, CasePorts.EvidenceFiles files, CaseSettings settings,
                       JsonMapper json, Clock clock) {
        this.jdbc = jdbc;
        this.store = store;
        this.threads = threads;
        this.managers = managers;
        this.targets = targets;
        this.files = files;
        this.settings = settings;
        this.clock = clock;
        this.json = json;
        this.detailQueries = new CaseDetailQueries(store, threads, targets, files, json, clock);
    }

    public ObjectNode page(ExecutionContext context, String scope, String status, Boolean archived, int page,
                           int pageSize) {
        long actor = actor(context);
        if (!"mine".equals(scope) && !"received".equals(scope)) {
            throw new BusinessError("INPUT_INVALID", 422, "scope 取值无效");
        }
        if (status != null && !List.of(CaseVocabulary.PENDING, CaseVocabulary.CLAIMED, CaseVocabulary.DECIDED)
                .contains(status)) {
            throw new BusinessError("INPUT_INVALID", 422, "status 取值无效");
        }
        if (page < 1 || pageSize < 1) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        if (pageSize > settings.getMaxPageSize()) {
            throw new BusinessError("INPUT_INVALID", 422, "page_size 超出上限");
        }
        String from = "mine".equals(scope)
                ? " from moderation_case c where c.case_type = 'report' and c.reporter_account_id = ?"
                : " from moderation_case c join case_appeal_eligibility e"
                + " on e.case_id = c.id and e.account_id = ? where c.case_type <> 'product_review'";
        var args = new ArrayList<Object>();
        args.add(actor);
        StringBuilder filter = new StringBuilder(from);
        if (status != null) {
            filter.append(" and c.case_status = ?");
            args.add(status);
        }
        if (archived != null) {
            filter.append(archived ? " and c.archived_at is not null" : " and c.archived_at is null");
        }
        long total = jdbc.sql("select count(*)" + filter).params(args.toArray()).query(Long.class).single();
        var pageArgs = new ArrayList<>(args);
        pageArgs.add(pageSize);
        pageArgs.add((long) (page - 1) * pageSize);
        var rows = jdbc.sql("""
                        select c.id, c.case_status, c.decision_kind, c.archived_at, c.public_result_at,
                               c.updated_at, c.case_type
                        """ + filter + " order by c.updated_at desc, c.id desc limit ? offset ?")
                .params(pageArgs.toArray()).query((rs, row) -> {
                    var item = json.createObjectNode();
                    item.put("case_id", Long.toString(rs.getLong("id")));
                    item.put("scope", scope);
                    item.put("case_type", rs.getString("case_type"));
                    item.put("case_status", rs.getString("case_status"));
                    item.put("decision_kind", rs.getString("decision_kind"));
                    item.put("archived_at", text(rs.getObject("archived_at", OffsetDateTime.class)));
                    item.put("public_result_at", text(rs.getObject("public_result_at", OffsetDateTime.class)));
                    item.put("updated_at", text(rs.getObject("updated_at", OffsetDateTime.class)));
                    var conversation = threads.findConversation(rs.getLong("id"), actor);
                    item.set("thread", conversation.isPresent()
                            ? thread(conversation.getAsLong()) : json.nullNode());
                    return item;
                }).list();
        var body = json.createObjectNode();
        var items = body.putArray("items");
        rows.forEach(items::add);
        body.put("page", page);
        body.put("page_size", pageSize);
        body.put("total", total);
        return body;
    }

    public long requireClaimedTrade(ExecutionContext context, long caseId) {
        long actor = actor(context);
        var facts = store.find(caseId).orElseThrow(CaseQueries::notVisible);
        if (!facts.lifecycle() || !facts.claimedBy(actor) || !managerRole(context)
                || !"trade".equals(facts.targetType()) || facts.targetId() == null) {
            throw notVisible();
        }
        return facts.targetId();
    }

    public ObjectNode detail(ExecutionContext context, long caseId) {
        return detailQueries.detail(detailAccess(context, caseId));
    }

    /**
     * Resolves the requester's viewpoint once and masks every unauthorized view as 404 before any
     * section is assembled. The order of the lookups is part of the read model.
     */
    private CaseDetailQueries.DetailAccess detailAccess(ExecutionContext context, long caseId) {
        long actor = actor(context);
        var facts = store.find(caseId).orElseThrow(CaseQueries::notVisible);
        if (!facts.lifecycle()) {
            throw notVisible();
        }
        boolean reporter = facts.reportedBy(actor);
        OptionalLong thread = facts.lifecycle()
                ? threads.findConversation(caseId, actor) : OptionalLong.empty();
        boolean related = thread.isPresent() || store.appealEligibility(caseId, actor).isPresent();
        boolean manager = facts.claimedBy(actor) && managerRole(context);
        if (!reporter && !related && !manager) {
            throw notVisible();
        }
        boolean reporterView = reporter;
        boolean relatedView = !reporter && related;
        boolean managerView = !reporter && !related && manager;
        return new CaseDetailQueries.DetailAccess(caseId, actor, facts, thread, reporter, related, manager,
                reporterView, relatedView, managerView);
    }

    /**
     * Reads one platform-record evidence body. Only the fixed claimant manager sees it, and the
     * stored scope plus the live message row must still agree with the reported target. Non-message
     * evidence, other managers, reporters and related accounts are all hidden as 404.
     */
    public ObjectNode referencedEvidence(ExecutionContext context, long caseId, long evidenceId) {
        long actor = actor(context);
        var facts = store.find(caseId).orElseThrow(CaseQueries::notVisible);
        if (!facts.lifecycle() || !facts.claimedBy(actor) || !managerRole(context)) {
            throw notVisible();
        }
        var evidence = store.evidence(caseId, evidenceId).orElseThrow(CaseQueries::notVisible);
        if (!CaseVocabulary.EVIDENCE_PLATFORM_RECORD.equals(evidence.evidenceKind())
                || !CaseVocabulary.SOURCE_MESSAGE.equals(evidence.sourceRefType())
                || evidence.sourceRefId() == null) {
            throw notVisible();
        }
        var scope = CaseRecords.MessageScope.parse(evidence.requiredScope())
                .orElseThrow(CaseQueries::notVisible);
        if (!CaseVocabulary.SOURCE_MESSAGE.equals(facts.targetType()) || facts.targetId() == null
                || !facts.targetId().equals(evidence.sourceRefId())
                || !scope.conversationKind().equals(facts.conversationKind())
                || facts.conversationId() == null || facts.conversationId() != scope.conversationId()) {
            throw notVisible();
        }
        CaseRecords.ReferencedMessage message;
        try {
            message = targets.requireReportedMessage(facts, scope.conversationKind(), scope.conversationId(),
                    evidence.sourceRefId());
        } catch (BusinessError denied) {
            throw notVisible();
        }
        var body = json.createObjectNode();
        body.put("evidence_id", Long.toString(evidence.evidenceId()));
        body.put("case_id", Long.toString(facts.caseId()));
        var source = body.putObject("source_ref");
        source.put("resource_type", CaseVocabulary.SOURCE_MESSAGE);
        source.put("resource_id", Long.toString(evidence.sourceRefId()));
        var conversation = body.putObject("conversation");
        conversation.put("conversation_kind", scope.conversationKind());
        conversation.put("conversation_id", Long.toString(scope.conversationId()));
        var item = body.putObject("message");
        item.put("message_id", Long.toString(message.messageId()));
        item.put("sender_kind", message.senderKind());
        if (message.senderAccountId() == null) {
            item.putNull("sender_account_id");
        } else {
            item.put("sender_account_id", Long.toString(message.senderAccountId()));
        }
        item.put("created_at", message.createdAt().toString());
        item.put("body", message.body());
        return body;
    }

    public ObjectNode results(ExecutionContext context, String targetType, Long targetId, String conversationKind,
                              Long conversationId, int page, int pageSize) {
        actor(context);
        if (page < 1 || pageSize < 1) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        if (pageSize > settings.getMaxPageSize()) {
            throw new BusinessError("INPUT_INVALID", 422, "page_size 超出上限");
        }
        var args = new ArrayList<Object>();
        var filter = new StringBuilder(" where public_result_at is not null and case_type = 'report'");
        if (targetType != null) {
            filter.append(" and target_type = ?");
            args.add(targetType);
            if (targetId != null) {
                filter.append(" and target_id = ?");
                args.add(targetId);
            }
            if ("message".equals(targetType)) {
                if (conversationKind == null || conversationId == null) {
                    throw new BusinessError("INPUT_INVALID", 422, "消息对象须同时给出会话类型与标识");
                }
                filter.append(" and target_conversation_kind = ? and target_conversation_id = ?");
                args.add(conversationKind);
                args.add(conversationId);
            }
        }
        long total = jdbc.sql("select count(*) from moderation_case" + filter)
                .params(args.toArray()).query(Long.class).single();
        var pageArgs = new ArrayList<>(args);
        pageArgs.add(pageSize);
        pageArgs.add((long) (page - 1) * pageSize);
        var items = jdbc.sql("""
                        select id, decision_kind, public_summary, public_reason, public_result_at
                        from moderation_case
                        """ + filter + " order by public_result_at desc, id desc limit ? offset ?")
                .params(pageArgs.toArray()).query((rs, row) -> {
                    var item = json.createObjectNode();
                    item.put("case_id", Long.toString(rs.getLong("id")));
                    item.put("decision_kind", rs.getString("decision_kind"));
                    item.put("public_summary", rs.getString("public_summary"));
                    item.put("public_reason", rs.getString("public_reason"));
                    item.put("published_at", text(rs.getObject("public_result_at", OffsetDateTime.class)));
                    return item;
                }).list();
        var body = json.createObjectNode();
        var array = body.putArray("items");
        items.forEach(array::add);
        body.put("page", page);
        body.put("page_size", pageSize);
        body.put("total", total);
        return body;
    }

    private boolean managerRole(ExecutionContext context) {
        try {
            managers.requireManager(context);
            return true;
        } catch (BusinessError denied) {
            return false;
        }
    }

    private ObjectNode thread(long conversationId) {
        var body = json.createObjectNode();
        body.put("conversation_kind", "case");
        body.put("conversation_id", Long.toString(conversationId));
        return body;
    }

    private static String text(Instant value) {
        return value == null ? null : value.toString();
    }

    private static String text(OffsetDateTime value) {
        return value == null ? null : value.toInstant().toString();
    }

    private static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
    }
}
