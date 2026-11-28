package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.OptionalLong;
import java.util.Set;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Response assembly for one case detail read. Access resolution and the 404 masking stay on
 * {@link CaseQueries}; this class owns the viewpoint-specific sections and preserves the read
 * order of the original single method.
 */
final class CaseDetailQueries {
    /** Actions with a real subject adapter that can reverse the original enforcement (API-CASE-008). */
    private static final Set<String> LIFTABLE_ACTIONS =
            Set.of("freeze_trade", "restrict_account", "withdraw_public_access");

    private final CaseLifecycleStore store;
    private final CasePorts.Threads threads;
    private final CasePorts.Targets targets;
    private final CasePorts.EvidenceFiles files;
    private final JsonMapper json;
    private final Clock clock;

    CaseDetailQueries(CaseLifecycleStore store, CasePorts.Threads threads, CasePorts.Targets targets,
                      CasePorts.EvidenceFiles files, JsonMapper json, Clock clock) {
        this.store = store;
        this.threads = threads;
        this.targets = targets;
        this.files = files;
        this.json = json;
        this.clock = clock;
    }

    ObjectNode detail(DetailAccess access) {
        var actions = store.actions(access.caseId());
        var pending = pendingInquiries(access.caseId());
        var inquiries = visibleInquiries(access, pending);
        var enforcements = store.enforcements(access.caseId());
        Instant now = clock.instant();
        var body = detailHeader(access);
        appendReporterMaterials(body, access, actions);
        appendManagerSnapshot(body, access);
        appendDecisionBasisActions(body, access, actions);
        appendAvailableActions(body, access, inquiries, now);
        appendPendingInquiries(body, access, inquiries);
        appendActionHistory(body, access, actions);
        appendEnforcements(body, access, enforcements);
        appendAppealDeadline(body, access);
        appendThread(body, access);
        appendEvidence(body, access);
        appendManagerAppeals(body, access, actions, enforcements);
        return body;
    }

    private static List<CaseRecords.Action> visibleInquiries(DetailAccess access,
                                                             List<CaseRecords.Action> pending) {
        if (access.facts().archived() || access.reporterView()) {
            return List.of();
        }
        if (access.relatedView()) {
            return pending.stream()
                    .filter(inquiry -> inquiry.relatedAccountId() != null
                            && inquiry.relatedAccountId() == access.actor())
                    .toList();
        }
        return pending;
    }

    private ObjectNode detailHeader(DetailAccess access) {
        var facts = access.facts();
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(facts.caseId()));
        body.put("case_type", facts.caseType());
        body.put("case_status", facts.caseStatus());
        body.put("decision_kind", facts.decisionKind());
        body.put("archived_at", text(facts.archivedAt()));
        body.put("public_result_at", text(facts.publicResultAt()));
        body.put("viewpoint", access.reporterView() ? CaseVocabulary.VIEWPOINT_REPORTER
                : access.relatedView() ? CaseVocabulary.VIEWPOINT_RELATED : CaseVocabulary.VIEWPOINT_MANAGER);
        body.put("reason_text", reasonText(facts, access.reporter(), access.related(), access.manager()));
        body.put("reported_reason", access.reporter() || access.manager() ? facts.reportedReason() : null);
        return body;
    }

    private void appendReporterMaterials(ObjectNode body, DetailAccess access,
                                         List<CaseRecords.Action> actions) {
        if (!access.reporterView()) {
            return;
        }
        var materials = body.putObject("report_materials");
        appendReportedProduct(materials, access);
        var supplements = materials.putArray("supplements");
        for (var action : actions) {
            if (!Long.valueOf(access.actor()).equals(action.actorAccountId())) {
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
        appendReporterAttachments(materials, access);
    }

    private void appendReportedProduct(ObjectNode materials, DetailAccess access) {
        targets.reportProduct(access.caseId()).ifPresent(snapshot -> {
            var product = materials.putObject("product");
            product.put("id", Long.toString(snapshot.id()));
            product.put("title", snapshot.title());
            product.put("description", snapshot.description());
        });
    }

    private void appendReporterAttachments(ObjectNode materials, DetailAccess access) {
        long caseId = access.caseId();
        var attachments = materials.putArray("attachments");
        for (var evidence : store.evidence(caseId)) {
            if (evidence.submittedAttachmentBy(access.actor())) {
                var item = attachments.addObject();
                item.put("evidence_id", Long.toString(evidence.evidenceId()));
                item.put("submitted_at", text(evidence.submittedAt()));
                files.contentType(caseId, evidence.fileId()).ifPresent(type -> item.put("content_type", type));
            }
        }
    }

    private void appendManagerSnapshot(ObjectNode body, DetailAccess access) {
        if (!access.managerView()) {
            return;
        }
        appendDispositionTargets(body, access);
        appendRelatedAccounts(body, access);
        appendReportedObject(body, access);
        appendReportedMessage(body, access);
        appendContentTarget(body, access);
    }

    private void appendDispositionTargets(ObjectNode body, DetailAccess access) {
        var facts = access.facts();
        if (facts.claimedBy(access.actor()) && CaseVocabulary.CLAIMED.equals(facts.caseStatus())
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
    }

    private void appendRelatedAccounts(ObjectNode body, DetailAccess access) {
        var facts = access.facts();
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
            account.put("eligible", relatedIds.contains(id) && id != access.actor()
                    && !Long.valueOf(id).equals(facts.reporterAccountId()));
        }
    }

    private void appendReportedObject(ObjectNode body, DetailAccess access) {
        var facts = access.facts();
        if (CaseVocabulary.REPORT.equals(facts.caseType()) && facts.targetId() != null) {
            var object = body.putObject("reported_object");
            object.put("target_type", facts.targetType());
            object.put("target_id", Long.toString(facts.targetId()));
            targets.reportProduct(access.caseId()).ifPresent(snapshot -> {
                var product = object.putObject("product");
                product.put("id", Long.toString(snapshot.id()));
                product.put("title", snapshot.title());
                product.put("description", snapshot.description());
            });
        }
    }

    private void appendReportedMessage(ObjectNode body, DetailAccess access) {
        var facts = access.facts();
        if ("message".equals(facts.targetType()) && facts.targetId() != null
                && facts.conversationId() != null && facts.conversationKind() != null) {
            var message = body.putObject("reported_message");
            message.put("conversation_kind", facts.conversationKind());
            message.put("conversation_id", Long.toString(facts.conversationId()));
            message.put("message_id", Long.toString(facts.targetId()));
        }
    }

    private void appendContentTarget(ObjectNode body, DetailAccess access) {
        targets.contentTarget(access.facts()).ifPresent(snapshot -> {
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

    private void appendDecisionBasisActions(ObjectNode body, DetailAccess access,
                                            List<CaseRecords.Action> actions) {
        if (!access.managerView()) {
            return;
        }
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

    private void appendAvailableActions(ObjectNode body, DetailAccess access,
                                        List<CaseRecords.Action> inquiries, Instant now) {
        var available = body.putArray("available_actions");
        var availableList = availableActions(access.facts(), access.reporterView(), access.relatedView(),
                access.managerView(), access.actor(), inquiries, now);
        availableList.forEach(available::add);
    }

    private void appendPendingInquiries(ObjectNode body, DetailAccess access,
                                        List<CaseRecords.Action> inquiries) {
        if (!access.relatedView() && !access.managerView()) {
            return;
        }
        var pendingItems = body.putArray("pending_inquiries");
        for (var inquiry : inquiries) {
            var item = pendingItems.addObject();
            item.put("inquiry_action_id", Long.toString(inquiry.actionId()));
            item.put("asked_at", text(inquiry.occurredAt()));
            item.put("scope_text", inquiry.note());
            if (access.managerView()) {
                item.put("related_account_id", inquiry.relatedAccountId() == null ? null
                        : Long.toString(inquiry.relatedAccountId()));
            }
        }
    }

    private void appendActionHistory(ObjectNode body, DetailAccess access,
                                     List<CaseRecords.Action> actions) {
        var actionArray = body.putArray("actions");
        for (var action : actions) {
            var item = actionArray.addObject();
            item.put("action_kind", action.actionKind());
            item.put("occurred_at", text(action.occurredAt()));
            item.put("actor_kind", action.actorKind());
            if (access.managerView()) {
                item.put("action_id", Long.toString(action.actionId()));
                if (action.messageId() != null && action.relatedAccountId() != null) {
                    item.put("message_id", Long.toString(action.messageId()));
                    item.put("related_account_id", Long.toString(action.relatedAccountId()));
                }
            }
        }
    }

    private void appendEnforcements(ObjectNode body, DetailAccess access,
                                    List<CaseRecords.Enforcement> enforcements) {
        var enforcementArray = body.putArray("enforcements");
        for (var enforcement : enforcements) {
            var item = enforcementArray.addObject();
            item.put("enforcement_id", enforcement.enforcementId());
            item.put("action", enforcement.action());
            item.put("result_status", enforcement.resultStatus());
            item.put("current_state", enforcement.currentState());
            if (access.manager()) {
                item.put("can_lift", canLift(enforcement));
            }
        }
    }

    private void appendAppealDeadline(ObjectNode body, DetailAccess access) {
        var deadline = store.appealEligibility(access.caseId(), access.actor())
                .map(element -> element.appealDeadlineAt())
                .orElse(null);
        body.put("appeal_deadline_at", text(deadline));
    }

    private void appendThread(ObjectNode body, DetailAccess access) {
        if (!access.reporterView() && access.thread().isPresent()) {
            body.set("thread", thread(access.thread().getAsLong()));
        } else {
            body.set("thread", json.nullNode());
        }
    }

    private void appendEvidence(ObjectNode body, DetailAccess access) {
        if (!access.manager() && !access.reporter()) {
            return;
        }
        long caseId = access.caseId();
        // A reporter without the manager role still receives the empty evidence array.
        var evidence = body.putArray("evidence");
        if (access.manager()) {
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

    private void appendManagerAppeals(ObjectNode body, DetailAccess access,
                                      List<CaseRecords.Action> actions,
                                      List<CaseRecords.Enforcement> enforcements) {
        if (!access.manager()) {
            return;
        }
        appendPendingAppeals(body, access, actions, enforcements);
        appendCaseThreads(body, access);
    }

    private void appendPendingAppeals(ObjectNode body, DetailAccess access,
                                      List<CaseRecords.Action> actions,
                                      List<CaseRecords.Enforcement> enforcements) {
        long caseId = access.caseId();
        var appeals = body.putArray("pending_appeals");
        if (access.facts().archived()) {
            return;
        }
        var resolved = actions.stream()
                .filter(action -> CaseVocabulary.ACTION_MANAGER_REPLY.equals(action.actionKind())
                        && action.appealActionId() != null)
                .map(result -> result.appealActionId()).collect(java.util.stream.Collectors.toSet());
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

    private void appendCaseThreads(ObjectNode body, DetailAccess access) {
        long caseId = access.caseId();
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

    private static boolean canLift(CaseRecords.Enforcement enforcement) {
        return "applied".equals(enforcement.resultStatus())
                && enforcement.liftedAt() == null
                && LIFTABLE_ACTIONS.contains(enforcement.action());
    }

    private static String reasonText(CaseRecords.Facts facts, boolean reporter, boolean related, boolean manager) {
        if (reporter) {
            return facts.publicReason();
        }
        if (related || manager) {
            return facts.reasonText();
        }
        return null;
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

    /** The resolved requester viewpoint; sections read the same facts and flags. */
    record DetailAccess(long caseId, long actor, CaseRecords.Facts facts, OptionalLong thread,
                        boolean reporter, boolean related, boolean manager,
                        boolean reporterView, boolean relatedView, boolean managerView) {
    }
}
