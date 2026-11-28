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
import java.util.LinkedHashSet;
import java.util.List;
import java.util.OptionalLong;
import java.util.Set;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Read side of the case lifecycle: personal lists, the viewpoint-trimmed detail projection and the
 * anonymous public results. Detail fields are computed from the caller's viewpoint; the query never
 * widens access after publication.
 */
public class CaseQueries {
    /** Actions with a real subject adapter that can reverse the original enforcement (API-CASE-008). */
    private static final Set<String> LIFTABLE_ACTIONS =
            Set.of("freeze_trade", "restrict_account", "withdraw_public_access");

    private final JdbcClient jdbc;
    private final CaseLifecycleStore store;
    private final CasePorts.Threads threads;
    private final CasePorts.Managers managers;
    private final CasePorts.Targets targets;
    private final CasePorts.EvidenceFiles files;
    private final CaseSettings settings;
    private final Clock clock;
    private final JsonMapper json;

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
        long actor = actor(context);
        var facts = store.find(caseId).orElseThrow(CaseQueries::notVisible);
        if (!facts.lifecycle()) {
            throw notVisible();
        }
        boolean reporter = facts.reportedBy(actor);
        OptionalLong thread = facts.lifecycle() ? threads.findConversation(caseId, actor) : OptionalLong.empty();
        boolean related = thread.isPresent() || store.appealEligibility(caseId, actor).isPresent();
        boolean manager = facts.claimedBy(actor) && managerRole(context);
        if (!reporter && !related && !manager) {
            throw notVisible();
        }
        boolean reporterView = reporter;
        boolean relatedView = !reporter && related;
        boolean managerView = !reporter && !related && manager;
        var actions = store.actions(caseId);
        var pending = pendingInquiries(caseId);
        List<CaseRecords.Action> inquiries;
        if (facts.archived() || reporterView) {
            inquiries = List.of();
        } else if (relatedView) {
            inquiries = pending.stream()
                    .filter(inquiry -> inquiry.relatedAccountId() != null && inquiry.relatedAccountId() == actor)
                    .toList();
        } else {
            inquiries = pending;
        }
        var enforcements = store.enforcements(caseId);
        Instant now = clock.instant();
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(facts.caseId()));
        body.put("case_type", facts.caseType());
        body.put("case_status", facts.caseStatus());
        body.put("decision_kind", facts.decisionKind());
        body.put("archived_at", text(facts.archivedAt()));
        body.put("public_result_at", text(facts.publicResultAt()));
        body.put("viewpoint", reporterView ? CaseVocabulary.VIEWPOINT_REPORTER
                : relatedView ? CaseVocabulary.VIEWPOINT_RELATED : CaseVocabulary.VIEWPOINT_MANAGER);
        body.put("reason_text", reasonText(facts, reporter, related, manager));
        body.put("reported_reason", reporter || manager ? facts.reportedReason() : null);
        if (reporterView) {
            var materials = body.putObject("report_materials");
            targets.reportProduct(caseId).ifPresent(snapshot -> {
                var product = materials.putObject("product");
                product.put("id", Long.toString(snapshot.id()));
                product.put("title", snapshot.title());
                product.put("description", snapshot.description());
            });
            var supplements = materials.putArray("supplements");
            for (var action : actions) {
                if (!Long.valueOf(actor).equals(action.actorAccountId())) {
                    continue;
                }
                if (CaseVocabulary.ACTION_SUBMIT.equals(action.actionKind())) {
                    materials.put("original_note", action.note());
                } else if (CaseVocabulary.ACTION_SUPPLEMENT.equals(action.actionKind()) && action.note() != null) {
                    var item = supplements.addObject();
                    item.put("action_id", Long.toString(action.actionId()));
                    item.put("note", action.note());
                    item.put("occurred_at", text(action.occurredAt()));
                }
            }
            var attachments = materials.putArray("attachments");
            for (var evidence : store.evidence(caseId)) {
                if (evidence.submittedAttachmentBy(actor)) {
                    var item = attachments.addObject();
                    item.put("evidence_id", Long.toString(evidence.evidenceId()));
                    item.put("submitted_at", text(evidence.submittedAt()));
                    files.contentType(caseId, evidence.fileId()).ifPresent(type -> item.put("content_type", type));
                }
            }
        }
        if (managerView) {
            if (facts.claimedBy(actor) && CaseVocabulary.CLAIMED.equals(facts.caseStatus())
                    && !facts.archived() && facts.targetId() != null) {
                var disposition = body.putObject("disposition_targets");
                disposition.put("target_type", facts.targetType());
                disposition.put("target_id", Long.toString(facts.targetId()));
                var products = disposition.putArray("products");
                for (var product : targets.dispositionProducts(facts)) {
                    var item = products.addObject();
                    item.put("id", Long.toString(product.id()));
                    item.put("title", product.title());
                }
            }
            var relatedIds = targets.relatedAccountIds(facts);
            var accountIds = new LinkedHashSet<>(relatedIds);
            if (facts.reporterAccountId() != null) {
                accountIds.add(facts.reporterAccountId());
            }
            var names = accountIds.isEmpty() ? java.util.Map.<Long, String>of() : targets.accountNames(accountIds);
            var accounts = body.putArray("related_accounts");
            for (long id : accountIds.stream().sorted().toList()) {
                var account = accounts.addObject();
                account.put("account_id", Long.toString(id));
                account.put("display_name", names.get(id));
                account.put("reporter", Long.valueOf(id).equals(facts.reporterAccountId()));
                account.put("eligible", relatedIds.contains(id) && id != actor
                        && !Long.valueOf(id).equals(facts.reporterAccountId()));
            }
            if (CaseVocabulary.REPORT.equals(facts.caseType()) && facts.targetId() != null) {
                var object = body.putObject("reported_object");
                object.put("target_type", facts.targetType());
                object.put("target_id", Long.toString(facts.targetId()));
                targets.reportProduct(caseId).ifPresent(snapshot -> {
                    var product = object.putObject("product");
                    product.put("id", Long.toString(snapshot.id()));
                    product.put("title", snapshot.title());
                    product.put("description", snapshot.description());
                });
            }
            if ("message".equals(facts.targetType()) && facts.targetId() != null
                    && facts.conversationId() != null && facts.conversationKind() != null) {
                var message = body.putObject("reported_message");
                message.put("conversation_kind", facts.conversationKind());
                message.put("conversation_id", Long.toString(facts.conversationId()));
                message.put("message_id", Long.toString(facts.targetId()));
            }
            targets.contentTarget(facts).ifPresent(snapshot -> {
                var target = body.putObject("target");
                target.put("target_type", snapshot.targetType());
                target.put("target_id", Long.toString(snapshot.targetId()));
                target.put("author_account_id", Long.toString(snapshot.authorAccountId()));
                if (snapshot.parentId() != null) {
                    target.put("parent_id", Long.toString(snapshot.parentId()));
                }
                if (snapshot.contextId() != null) {
                    target.put("context_id", Long.toString(snapshot.contextId()));
                }
                target.put("body", snapshot.body());
                target.put("state", snapshot.state());
                target.put("created_at", text(snapshot.createdAt()));
                target.put("removed", snapshot.removed());
            });
        }
        if (managerView) {
            var choices = body.putArray("decision_basis_actions");
            for (var action : actions) {
                if (!action.decisionBasis()) {
                    continue;
                }
                var item = choices.addObject();
                item.put("action_id", Long.toString(action.actionId()));
                item.put("action_kind", action.actionKind());
                item.put("occurred_at", text(action.occurredAt()));
                item.put("note", action.note());
            }
        }
        var available = body.putArray("available_actions");
        var availableList = availableActions(facts, reporterView, relatedView, managerView, actor, inquiries, now);
        availableList.forEach(available::add);
        if (relatedView || managerView) {
            var pendingItems = body.putArray("pending_inquiries");
            for (var inquiry : inquiries) {
                var item = pendingItems.addObject();
                item.put("inquiry_action_id", Long.toString(inquiry.actionId()));
                item.put("asked_at", text(inquiry.occurredAt()));
                item.put("scope_text", inquiry.note());
                if (managerView) {
                    item.put("related_account_id", inquiry.relatedAccountId() == null ? null
                            : Long.toString(inquiry.relatedAccountId()));
                }
            }
        }
        var actionArray = body.putArray("actions");
        for (var action : actions) {
            var item = actionArray.addObject();
            item.put("action_kind", action.actionKind());
            item.put("occurred_at", text(action.occurredAt()));
            item.put("actor_kind", action.actorKind());
            if (managerView) {
                item.put("action_id", Long.toString(action.actionId()));
                if (action.messageId() != null && action.relatedAccountId() != null) {
                    item.put("message_id", Long.toString(action.messageId()));
                    item.put("related_account_id", Long.toString(action.relatedAccountId()));
                }
            }
        }
        var enforcementArray = body.putArray("enforcements");
        for (var enforcement : enforcements) {
            var item = enforcementArray.addObject();
            item.put("enforcement_id", enforcement.enforcementId());
            item.put("action", enforcement.action());
            item.put("result_status", enforcement.resultStatus());
            item.put("current_state", enforcement.currentState());
            if (manager) {
                item.put("can_lift", canLift(enforcement));
            }
        }
        var deadline = store.appealEligibility(caseId, actor).map(CaseRecords.AppealEligibility::appealDeadlineAt)
                .orElse(null);
        body.put("appeal_deadline_at", text(deadline));
        if (!reporterView && thread.isPresent()) {
            body.set("thread", thread(thread.getAsLong()));
        } else {
            body.set("thread", json.nullNode());
        }
        if (manager || reporter) {
            var evidence = body.putArray("evidence");
            if (manager) {
                for (var item : store.evidence(caseId)) {
                    var entry = evidence.addObject();
                    entry.put("evidence_id", Long.toString(item.evidenceId()));
                    entry.put("evidence_kind", item.evidenceKind());
                    entry.put("submitted_at", text(item.submittedAt()));
                    entry.put("decision_basis", item.decisionBasis());
                    entry.put("file_id", item.fileId() == null ? null : Long.toString(item.fileId()));
                    if (item.fileId() != null) {
                        files.contentType(caseId, item.fileId()).ifPresent(type -> entry.put("content_type", type));
                    }
                }
            }
        }
        if (manager) {
            var appeals = body.putArray("pending_appeals");
            if (!facts.archived()) {
                var resolved = actions.stream()
                        .filter(action -> CaseVocabulary.ACTION_MANAGER_REPLY.equals(action.actionKind())
                                && action.appealActionId() != null)
                        .map(CaseRecords.Action::appealActionId).collect(java.util.stream.Collectors.toSet());
                for (var action : actions) {
                    if (!CaseVocabulary.ACTION_APPEAL.equals(action.actionKind())
                            || action.relatedAccountId() == null || resolved.contains(action.actionId())) {
                        continue;
                    }
                    threads.findConversation(caseId, action.relatedAccountId()).ifPresent(conversationId -> {
                        var appeal = appeals.addObject();
                        appeal.put("appeal_action_id", Long.toString(action.actionId()));
                        appeal.put("related_account_id", Long.toString(action.relatedAccountId()));
                        appeal.put("submitted_at", text(action.occurredAt()));
                        var eligible = appeal.putArray("original_enforcements");
                        for (var enforcement : eligibleOriginalEnforcements(caseId, action.relatedAccountId(),
                                enforcements)) {
                            var item = eligible.addObject();
                            item.put("enforcement_id", enforcement.enforcementId());
                            item.put("action", enforcement.action());
                            item.put("target_type", enforcement.targetType());
                            item.put("target_id", Long.toString(enforcement.targetId()));
                        }
                        appeal.set("thread", thread(conversationId));
                    });
                }
            }
            var threadsArray = body.putArray("threads");
            for (long accountId : store.relatedAccountIds(caseId)) {
                var conversation = threads.findConversation(caseId, accountId);
                if (conversation.isPresent()) {
                    var item = threadsArray.addObject();
                    item.put("related_account_id", Long.toString(accountId));
                    item.put("conversation_kind", "case");
                    item.put("conversation_id", Long.toString(conversation.getAsLong()));
                }
            }
        }
        return body;
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

    /**
     * Active applied original executions that affected the appealing account. Reversal records,
     * already lifted records and terminal trade adjustments are not offered because they cannot be
     * revoked or adjusted again.
     */
    private List<CaseRecords.Enforcement> eligibleOriginalEnforcements(long caseId, long accountId,
                                                                       List<CaseRecords.Enforcement> enforcements) {
        return enforcements.stream()
                .filter(item -> item.affectedAccountIds().contains(accountId))
                .filter(item -> "applied".equals(item.resultStatus()))
                .filter(item -> LIFTABLE_ACTIONS.contains(item.action()))
                .filter(item -> item.basisRef() == null || !item.basisRef().contains(":replacement"))
                .filter(item -> store.lift(caseId, item.enforcementId()).isEmpty())
                .toList();
    }

    private List<CaseRecords.Action> pendingInquiries(long caseId) {
        return store.actions(caseId).stream()
                .filter(action -> CaseVocabulary.ACTION_INQUIRE.equals(action.actionKind()))
                .filter(action -> !store.statementExists(caseId, action.actionId()))
                .toList();
    }

    private Set<String> availableActions(CaseRecords.Facts facts, boolean reporterView, boolean relatedView,
                                         boolean managerView, long actor, List<CaseRecords.Action> inquiries,
                                         Instant now) {
        var actions = new LinkedHashSet<String>();
        if (reporterView && !facts.archived() && !facts.decided()) {
            actions.add(CaseVocabulary.SUPPLEMENT_EVIDENCE);
        }
        if (relatedView && !facts.archived()) {
            if (inquiries.stream().anyMatch(inquiry -> inquiry.relatedAccountId() != null
                    && inquiry.relatedAccountId() == actor)) {
                actions.add(CaseVocabulary.RESPOND_INQUIRY);
            }
            var eligibility = store.appealEligibility(facts.caseId(), actor);
            if (eligibility.isPresent() && !facts.archived() && facts.decided()
                    && !now.isAfter(eligibility.get().appealDeadlineAt())
                    && !store.hasPendingAppeal(facts.caseId(), actor)) {
                actions.add(CaseVocabulary.SUBMIT_APPEAL);
            }
        }
        if (managerView) {
            if (!facts.archived() && facts.claimedBy(actor)) {
                actions.add(CaseVocabulary.INQUIRE);
            }
            if (facts.claimedBy(actor) && CaseVocabulary.CLAIMED.equals(facts.caseStatus()) && !facts.archived()) {
                actions.add(CaseVocabulary.DECIDE);
            }
            if (facts.claimedBy(actor) && !facts.archived() && store.latestPendingAppeal(facts.caseId()).isPresent()) {
                actions.add(CaseVocabulary.RESOLVE_APPEAL);
            }
            if (facts.claimedBy(actor) && facts.decided() && !facts.archived() && canClose(facts, now)) {
                actions.add(CaseVocabulary.CLOSE);
            }
            if (facts.claimedBy(actor) && facts.archived() && facts.publicResultAt() == null
                    && CaseVocabulary.REPORT.equals(facts.caseType())) {
                actions.add(CaseVocabulary.PUBLISH_RESULT);
            }
        }
        return actions;
    }

    private boolean canClose(CaseRecords.Facts facts, Instant now) {
        for (var eligibility : store.appealEligibilities(facts.caseId())) {
            if (now.isBefore(eligibility.appealDeadlineAt())) {
                return false;
            }
        }
        return store.latestPendingAppeal(facts.caseId()).isEmpty();
    }

    private String reasonText(CaseRecords.Facts facts, boolean reporter, boolean related, boolean manager) {
        if (reporter) {
            return facts.publicReason();
        }
        if (related || manager) {
            return facts.reasonText();
        }
        return null;
    }

    private static boolean canLift(CaseRecords.Enforcement enforcement) {
        return "applied".equals(enforcement.resultStatus())
                && enforcement.liftedAt() == null
                && LIFTABLE_ACTIONS.contains(enforcement.action());
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
