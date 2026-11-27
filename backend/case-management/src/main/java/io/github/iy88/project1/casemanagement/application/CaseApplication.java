package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseSettings;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Report, dispute and exception lifecycle: submission, fixed claim, inquiry, statement, appeal,
 * decision, close and anonymous publication. The shared {@link WriteExecutor} owns each
 * transaction and idempotency scope; conversation threads and subject execution stay behind the
 * ports supplied by their modules.
 *
 * <p>Every message and decision path locks the case row before touching a thread, so the case
 * lock also serializes the threads of one case. Subject execution is delegated to the enforcement
 * port and persisted as case links in the same transaction; a missing port fails the decision
 * instead of recording an execution that did not happen.</p>
 */
public class CaseApplication {
    public static final String SUBMIT = "case.report.submit";
    public static final String SUPPLEMENT = "case.report.supplement";
    public static final String CLAIM = "case.claim";
    public static final String INQUIRE = "case.inquire";
    public static final String MESSAGE = "case.message";
    public static final String DECIDE = "case.decide";
    public static final String CLOSE = "case.close";
    public static final String PUBLISH = "case.publish_result";
    public static final String LIFT = "case.enforcement.lift";
    public static final String REFERENCE_EVIDENCE = "case.evidence.reference";

    private static final Set<String> ENFORCEMENT_ACTIONS = Set.of(
            "restrict_account", "lift_account_restriction", "withdraw_public_access", "restore_display",
            "remove_content", "freeze_trade", "lift_trade_freeze", "adjust_trade_status",
            "remove_evaluation_content");
    private static final Set<String> TRADE_ACTIONS = Set.of("freeze_trade", "lift_trade_freeze",
            "adjust_trade_status");
    /** Records produced by a reversal, never selectable as the original enforcement. */
    private static final Set<String> LIFT_ACTIONS = Set.of("lift_account_restriction", "restore_display",
            "lift_trade_freeze");
    /** A terminal trade adjustment cannot be reversed or adjusted again. */
    private static final Set<String> TERMINAL_ACTIONS = Set.of("adjust_trade_status");
    /** Original actions whose subject handlers can compensate; other content removals cannot. */
    private static final Set<String> REVERSIBLE_ACTIONS = Set.of("freeze_trade", "restrict_account",
            "withdraw_public_access");
    private static final Set<String> ADJUST_TRADE_TARGETS = Set.of("completed", "terminated", "in_progress");

    private final WriteExecutor writes;
    private final CaseLifecycleStore store;
    private final CasePorts.Targets targets;
    private final CasePorts.Managers managers;
    private final CasePorts.Accounts accounts;
    private final CasePorts.Notifications notifications;
    private final CasePorts.Threads threads;
    private final CasePorts.EvidenceFiles files;
    private final CasePorts.Enforcement enforcement;
    private final CaseSettings settings;
    private final JsonMapper json;
    private final Clock clock;

    public CaseApplication(WriteExecutor writes, CaseLifecycleStore store, CasePorts.Targets targets,
                           CasePorts.Managers managers, CasePorts.Accounts accounts,
                           CasePorts.Notifications notifications, CasePorts.Threads threads,
                           CasePorts.EvidenceFiles files, CasePorts.Enforcement enforcement,
                           CaseSettings settings, JsonMapper json, Clock clock) {
        this.writes = Objects.requireNonNull(writes);
        this.store = Objects.requireNonNull(store);
        this.targets = Objects.requireNonNull(targets);
        this.managers = Objects.requireNonNull(managers);
        this.accounts = Objects.requireNonNull(accounts);
        this.notifications = Objects.requireNonNull(notifications);
        this.threads = Objects.requireNonNull(threads);
        this.files = Objects.requireNonNull(files);
        this.enforcement = enforcement;
        this.settings = Objects.requireNonNull(settings);
        this.json = Objects.requireNonNull(json);
        this.clock = Objects.requireNonNull(clock);
    }

    public WriteResult<JsonNode> submit(ExecutionContext context, String idempotencyKey, CaseCommands.Report report) {
        return writes.run(context, SUBMIT, idempotencyKey, report, new SubmitUseCase());
    }

    public WriteResult<JsonNode> supplement(ExecutionContext context, String idempotencyKey, long caseId,
                                            CaseCommands.Supplement supplement) {
        return writes.run(context, SUPPLEMENT, idempotencyKey, new SupplementRequest(caseId, supplement),
                new SupplementUseCase());
    }

    public WriteResult<JsonNode> claim(ExecutionContext context, String idempotencyKey, long caseId) {
        managers.requireManager(context);
        return writes.run(context, CLAIM, idempotencyKey, new ClaimRequest(caseId), new ClaimUseCase());
    }

    public WriteResult<JsonNode> inquire(ExecutionContext context, String idempotencyKey, long caseId,
                                         CaseCommands.Inquiry inquiry) {
        managers.requireManager(context);
        return writes.run(context, INQUIRE, idempotencyKey, new InquiryRequest(caseId, inquiry),
                new InquiryUseCase());
    }

    public WriteResult<JsonNode> postMessage(ExecutionContext context, String idempotencyKey, long caseId,
                                             CaseCommands.Message message) {
        if (CaseVocabulary.KIND_MANAGER_REPLY.equals(message.messageKind())) {
            managers.requireManager(context);
        }
        return writes.run(context, MESSAGE, idempotencyKey, new MessageRequest(caseId, message),
                new MessageUseCase());
    }

    public WriteResult<JsonNode> decide(ExecutionContext context, String idempotencyKey, long caseId,
                                        CaseCommands.Decision decision) {
        managers.requireManager(context);
        return writes.run(context, DECIDE, idempotencyKey, new DecisionRequest(caseId, decision),
                new DecisionUseCase());
    }

    public WriteResult<JsonNode> close(ExecutionContext context, String idempotencyKey, long caseId) {
        managers.requireManager(context);
        return writes.run(context, CLOSE, idempotencyKey, new CloseRequest(caseId), new CloseUseCase());
    }

    public WriteResult<JsonNode> publish(ExecutionContext context, String idempotencyKey, long caseId,
                                         CaseCommands.Publish publish) {
        managers.requireManager(context);
        return writes.run(context, PUBLISH, idempotencyKey, new PublishRequest(caseId, publish),
                new PublishUseCase());
    }

    /** API-CASE-008: lifts one recorded enforcement by its case-stable execution identifier. */
    public WriteResult<JsonNode> lift(ExecutionContext context, String idempotencyKey, long caseId,
                                      String enforcementId, String reason) {
        managers.requireManager(context);
        return writes.run(context, LIFT, idempotencyKey, new LiftRequest(caseId, enforcementId, reason),
                new LiftUseCase());
    }

    /**
     * References the exact message reported by this case as a manager-owned platform record. The
     * manager must already be the case's fixed claimant; every other caller is hidden as 404.
     */
    public WriteResult<JsonNode> referenceEvidence(ExecutionContext context, String idempotencyKey, long caseId,
                                                   CaseCommands.EvidenceReference reference) {
        return writes.run(context, REFERENCE_EVIDENCE, idempotencyKey,
                new EvidenceReferenceRequest(caseId, reference), new EvidenceReferenceUseCase());
    }

    private record SupplementRequest(long caseId, CaseCommands.Supplement supplement) {
    }

    private record ClaimRequest(long caseId) {
    }

    private record InquiryRequest(long caseId, CaseCommands.Inquiry inquiry) {
    }

    private record MessageRequest(long caseId, CaseCommands.Message message) {
    }

    private record DecisionRequest(long caseId, CaseCommands.Decision decision) {
    }

    private record CloseRequest(long caseId) {
    }

    private record PublishRequest(long caseId, CaseCommands.Publish publish) {
    }

    private record LiftRequest(long caseId, String enforcementId, String reason) {
    }

    private record EvidenceReferenceRequest(long caseId, CaseCommands.EvidenceReference reference) {
    }

    // ------------------------------------------------------------------ submit and supplement

    private final class SubmitUseCase implements WriteExecutor.UseCase<CaseCommands.Report, CaseCommands.Report> {
        @Override
        public JsonNode digestInput(CaseCommands.Report request) {
            ObjectNode digest = json.valueToTree(request);
            if (request.target().sourceProductId() == null) {
                ((ObjectNode) digest.get("target")).remove("source_product_id");
                ((ObjectNode) digest.get("target")).remove("sourceProductId");
            }
            return digest;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, CaseCommands.Report request) {
            var plan = fileLocks(request.attachments());
            var existing = store.findOpenReport(actor(context), request.target());
            if (existing.isPresent()) {
                plan = plan.merge(new LockPlan(Map.of(), Set.of(
                        CaseLifecycleStore.lockKey(existing.get().caseId()))));
            }
            return plan;
        }

        @Override
        public CaseCommands.Report qualify(ExecutionContext context, CaseCommands.Report request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, CaseCommands.Report qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.reportedBy(actor(context))) {
                throw notVisible();
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, CaseCommands.Report request,
                                             CaseCommands.Report qualification, LockPlan plan) {
            long reporter = actor(transaction.context());
            if (accounts.writeRestricted(reporter)) {
                throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前受限");
            }
            targets.requireReportable(request.target(), reporter);
            String reason = requiredText(request.reason(), settings.getMaxReasonLength(), "举报原因");
            String note = optionalText(request.note(), settings.getMaxNoteLength(), "补充说明");
            Instant now = now();
            var existing = store.findOpenReport(reporter, request.target());
            if (existing.isPresent()) {
                long caseId = existing.get().caseId();
                var facts = store.lock(transaction, caseId);
                requireLifecycle(facts);
                if (!facts.archived() && !facts.decided()) {
                    Long firstEvidence = attachEvidence(transaction, caseId, reporter, request.attachments());
                    store.addAction(new CaseRecords.Action(0, caseId, CaseVocabulary.ACTION_SUPPLEMENT,
                            CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null), note == null ? firstEvidence : null);
                    store.touch(caseId, now);
                    audit(transaction, "case.report.supplement", caseId, reporter);
                    return new WriteResult.Response<>(200,
                            submitted(caseId, facts.caseStatus(), true), new ResourceRef("case", caseId));
                }
            }
            lockFiles(transaction, request.attachments());
            Long opened = store.openReportIfAbsent(request.target(), reporter, reason, now).orElse(null);
            if (opened == null) {
                var current = store.findOpenReport(reporter, request.target()).orElseThrow(CaseApplication::conflict);
                var facts = store.lock(transaction, current.caseId());
                if (facts.archived() || facts.decided()) throw conflict();
                Long firstEvidence = attachEvidence(transaction, facts.caseId(), reporter, request.attachments());
                store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_SUPPLEMENT,
                        CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null), note == null ? firstEvidence : null);
                store.touch(facts.caseId(), now);
                audit(transaction, "case.report.supplement", facts.caseId(), reporter);
                return new WriteResult.Response<>(200, submitted(facts.caseId(), facts.caseStatus(), true),
                        new ResourceRef("case", facts.caseId()));
            }
            long caseId = opened;
            targets.captureReportSnapshot(caseId, request.target());
            store.addAction(new CaseRecords.Action(0, caseId, CaseVocabulary.ACTION_SUBMIT,
                    CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null));
            attachEvidence(transaction, caseId, reporter, request.attachments());
            audit(transaction, "case.report.submit", caseId, reporter);
            return new WriteResult.Response<>(201, submitted(caseId, CaseVocabulary.PENDING, false),
                    new ResourceRef("case", caseId));
        }
    }

    private final class SupplementUseCase implements WriteExecutor.UseCase<SupplementRequest, SupplementRequest> {
        @Override
        public JsonNode digestInput(SupplementRequest request) {
            return digest(request.caseId(), request.supplement());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, SupplementRequest request) {
            return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())))
                    .merge(fileLocks(request.supplement().attachments()));
        }

        @Override
        public SupplementRequest qualify(ExecutionContext context, SupplementRequest request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, SupplementRequest qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.reportedBy(actor(context))) {
                throw notVisible();
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, SupplementRequest request,
                                             SupplementRequest qualification, LockPlan plan) {
            long reporter = actor(transaction.context());
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (!facts.reportedBy(reporter)) {
                throw new BusinessError("NOT_CASE_PARTICIPANT", 404, "事项不可见");
            }
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            if (facts.decided()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项已作出决定，请重新提交举报");
            }
            String note = optionalText(request.supplement().note(), settings.getMaxNoteLength(), "补充说明");
            if (note == null && request.supplement().attachments().isEmpty()) {
                throw new BusinessError("INPUT_INVALID", 422, "补充材料不能为空");
            }
            lockFiles(transaction, request.supplement().attachments());
            Instant now = now();
            Long firstEvidence = attachEvidence(transaction, facts.caseId(), reporter, request.supplement().attachments());
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_SUPPLEMENT,
                    CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null), note == null ? firstEvidence : null);
            store.touch(facts.caseId(), now);
            audit(transaction, "case.report.supplement", facts.caseId(), reporter);
            long supplements = store.actions(facts.caseId()).stream()
                    .filter(action -> CaseVocabulary.ACTION_SUPPLEMENT.equals(action.actionKind()))
                    .count();
            var body = json.createObjectNode();
            body.put("case_id", Long.toString(facts.caseId()));
            body.put("supplement_count", supplements);
            body.put("updated_at", now.toString());
            return new WriteResult.Response<>(200, body, new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ claim

    private final class ClaimUseCase implements WriteExecutor.UseCase<ClaimRequest, Boolean> {
        @Override
        public JsonNode digestInput(ClaimRequest request) {
            return json.createObjectNode().put("case_id", request.caseId());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, ClaimRequest request) {
            return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())));
        }

        @Override
        public Boolean qualify(ExecutionContext context, ClaimRequest request, LockPlan plan) {
            managers.requireManagerForWrite(context);
            return Boolean.TRUE;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, Boolean qualification, ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw notVisible();
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, ClaimRequest request,
                                             Boolean qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            boolean alreadyClaimed = facts.claimedBy(manager);
            if (!alreadyClaimed) {
                if (facts.claimedManagerId() != null) {
                    throw new BusinessError("CASE_ALREADY_CLAIMED", 409, "事项已被其他管理员认领");
                }
                facts = store.claim(facts.caseId(), manager, now());
                store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_CLAIM,
                        CaseVocabulary.ACTOR_MANAGER, manager, now(), null, null, null, null, null, null, null));
            }
            audit(transaction, "case.claim", facts.caseId(), manager);
            var body = json.createObjectNode();
            body.put("case_id", Long.toString(facts.caseId()));
            body.put("case_status", facts.caseStatus());
            body.put("claimed_manager_id", Long.toString(facts.claimedManagerId()));
            body.put("claimed_at", facts.claimedAt().toString());
            body.put("already_claimed", alreadyClaimed);
            return new WriteResult.Response<>(200, body, new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ inquiry

    private final class InquiryUseCase implements WriteExecutor.UseCase<InquiryRequest, InquiryRequest> {
        @Override
        public JsonNode digestInput(InquiryRequest request) {
            return digest(request.caseId(), request.inquiry());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, InquiryRequest request) {
            var facts = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
            var resources = new TreeSet<LockPlan.Key>();
            resources.add(CaseLifecycleStore.lockKey(facts.caseId()));
            threads.findConversation(facts.caseId(), request.inquiry().peerAccountId())
                    .ifPresent(id -> resources.add(new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION,
                            List.of(id))));
            var accounts = new TreeMap<Long, LockPlan.AccountMode>();
            if (request.inquiry().peerAccountId() > 0) {
                accounts.put(request.inquiry().peerAccountId(), LockPlan.AccountMode.SHARED);
            }
            return new LockPlan(accounts, resources);
        }

        @Override
        public InquiryRequest qualify(ExecutionContext context, InquiryRequest request, LockPlan plan) {
            managers.requireManagerForWrite(context);
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, InquiryRequest qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, InquiryRequest request,
                                             InquiryRequest qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (!facts.claimedBy(manager)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            long peer = request.inquiry().peerAccountId();
            if (peer <= 0 || peer == manager) {
                throw new BusinessError("INPUT_INVALID", 422, "问询对象无效");
            }
            if (facts.reporterAccountId() != null && facts.reporterAccountId() == peer) {
                throw new BusinessError("INPUT_INVALID", 422, "不得向举报人发起问询");
            }
            if (!targets.relatedAccountIds(facts).contains(peer)) {
                throw new BusinessError("INPUT_INVALID", 422, "对象不是事项相关账户");
            }
            String scope = requiredText(request.inquiry().scopeText(), settings.getMaxNoteLength(), "问询范围");
            Instant now = now();
            long conversationId = threads.ensure(transaction, facts.caseId(), peer);
            var message = threads.append(transaction, facts.caseId(), peer, CaseVocabulary.KIND_INQUIRY,
                    CaseVocabulary.ACTOR_MANAGER, manager, scope);
            long actionId = store.addAction(new CaseRecords.Action(0, facts.caseId(),
                    CaseVocabulary.ACTION_INQUIRE, CaseVocabulary.ACTOR_MANAGER, manager, now,
                    message.messageId(), peer, null, null, null, scope, null));
            notifications.create(transaction, CaseVocabulary.EVENT_INQUIRY_CREATED,
                    "case:" + facts.caseId() + ":inquiry:" + actionId, new ResourceRef("case", facts.caseId()),
                    Set.of(peer), Map.of("case_id", Long.toString(facts.caseId())), now);
            store.touch(facts.caseId(), now);
            audit(transaction, "case.inquire", facts.caseId(), manager);
            var body = json.createObjectNode();
            body.put("inquiry_action_id", Long.toString(actionId));
            body.put("case_message_id", Long.toString(message.messageId()));
            body.set("thread", thread(conversationId));
            body.put("case_status", facts.caseStatus());
            body.put("notified_at", now.toString());
            return new WriteResult.Response<>(201, body, new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ statement, appeal, manager reply

    private final class MessageUseCase implements WriteExecutor.UseCase<MessageRequest, MessageRequest> {
        @Override
        public JsonNode digestInput(MessageRequest request) {
            return digest(request.caseId(), request.message());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, MessageRequest request) {
            var facts = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
            var resources = new TreeSet<LockPlan.Key>();
            resources.add(CaseLifecycleStore.lockKey(facts.caseId()));
            if (request.message().conversationId() != null) {
                resources.add(new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION,
                        List.of(request.message().conversationId())));
            }
            var message = request.message();
            if (CaseVocabulary.KIND_MANAGER_REPLY.equals(message.messageKind())) {
                addCaseThreadLocks(facts.caseId(), resources);
            }
            var plan = new LockPlan(Map.of(), resources);
            if (enforcement != null && reversal(message) && facts.claimedBy(actor(context))) {
                var appellant = appellantFor(facts.caseId(), message.appealActionId());
                if (appellant != null) {
                    // Prepare only plans the rows for the selected record. Active/unlifted
                    // eligibility is mutable and deliberately checked after the case lock so a
                    // replayed resolution still returns its original response.
                    var recorded = selectedEnforcement(facts.caseId(), message.originalEnforcementId(),
                            appellant, false);
                    if (recorded != null) {
                        plan = plan.merge(enforcement.reverseLockCallbacks(context, facts.caseId(), recorded,
                                message.resolution()).lockPlan());
                        if (CaseVocabulary.RESOLUTION_ADJUST.equals(message.resolution())) {
                            var replacements = replacementInstructions(message, recorded);
                            if (!replacements.isEmpty()) {
                                plan = plan.merge(enforcement.lockCallbacks(context, facts.caseId(),
                                        replacements).lockPlan());
                            }
                        }
                    }
                }
            }
            return plan;
        }

        @Override
        public MessageRequest qualify(ExecutionContext context, MessageRequest request, LockPlan plan) {
            if (CaseVocabulary.KIND_MANAGER_REPLY.equals(request.message().messageKind())) {
                managers.requireManagerForWrite(context);
            }
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, MessageRequest qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            long actor = actor(context);
            boolean manager = facts.claimedBy(actor);
            boolean related = facts.lifecycle() && threads.findConversation(facts.caseId(), actor).isPresent();
            if (!manager && !related) {
                throw notVisible();
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, MessageRequest request,
                                             MessageRequest qualification, LockPlan plan) {
            var message = request.message();
            long actor = actor(transaction.context());
            CaseRecords.Facts facts;
            if (enforcement != null && reversal(message)) {
                // Keep the authorization error ahead of the reversal selection so a caller who is
                // not the claimed manager still sees NOT_CASE_MANAGER.
                var preflight = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
                if (!preflight.claimedBy(actor)) {
                    throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
                }
                var appellant = appellantFor(request.caseId(), message.appealActionId());
                var recorded = appellant == null ? null : selectedEnforcement(request.caseId(),
                        message.originalEnforcementId(), appellant, false);
                var subjects = recorded == null ? SubjectPlan.empty()
                        : enforcement.reverseLockCallbacks(transaction.context(), request.caseId(),
                        recorded, message.resolution());
                if (recorded != null && CaseVocabulary.RESOLUTION_ADJUST.equals(message.resolution())) {
                    subjects = subjects.merge(enforcement.lockCallbacks(transaction.context(), request.caseId(),
                            replacementInstructions(message, recorded)));
                }
                facts = acquireSubjectLocks(transaction, plan, subjects, request.caseId());
            } else {
                facts = store.lock(transaction, request.caseId());
            }
            requireLifecycle(facts);
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            return switch (message.messageKind()) {
                case CaseVocabulary.KIND_STATEMENT -> statement(transaction, facts, actor, message);
                case CaseVocabulary.KIND_APPEAL -> appeal(transaction, facts, actor, message);
                case CaseVocabulary.KIND_MANAGER_REPLY -> managerReply(transaction, facts, actor, message, plan);
                default -> throw new BusinessError("INPUT_INVALID", 422, "message_kind 取值无效");
            };
        }

        private WriteResult.Response<?> statement(WriteTransaction transaction, CaseRecords.Facts facts,
                                                  long actor, CaseCommands.Message message) {
            rejectResolutionFields(message);
            if (message.inquiryActionId() == null) {
                throw new BusinessError("INPUT_INVALID", 422, "说明须引用问询标识");
            }
            long conversationId = requireThread(facts.caseId(), actor, message.conversationId());
            var inquiry = store.action(facts.caseId(), message.inquiryActionId())
                    .orElseThrow(() -> new BusinessError("INPUT_INVALID", 422, "问询不存在"));
            if (!CaseVocabulary.ACTION_INQUIRE.equals(inquiry.actionKind())
                    || inquiry.relatedAccountId() == null || inquiry.relatedAccountId() != actor) {
                throw new BusinessError("INPUT_INVALID", 422, "问询不属于当前账户");
            }
            if (store.statementExists(facts.caseId(), inquiry.actionId())) {
                throw new BusinessError("STATE_CONFLICT", 409, "该问询已回复");
            }
            Instant now = now();
            var appended = threads.append(transaction, facts.caseId(), actor, CaseVocabulary.KIND_STATEMENT,
                    CaseVocabulary.ACTOR_ACCOUNT, actor, message.body());
            long actionId = store.addAction(new CaseRecords.Action(0, facts.caseId(),
                    CaseVocabulary.ACTION_STATEMENT, CaseVocabulary.ACTOR_ACCOUNT, actor, now,
                    appended.messageId(), actor, inquiry.actionId(), null, null, null, null));
            store.touch(facts.caseId(), now);
            audit(transaction, "case.statement", facts.caseId(), actor);
            return messageResponse(facts, conversationId, appended, actionId, CaseVocabulary.KIND_STATEMENT);
        }

        private WriteResult.Response<?> appeal(WriteTransaction transaction, CaseRecords.Facts facts,
                                               long actor, CaseCommands.Message message) {
            rejectResolutionFields(message);
            if (message.inquiryActionId() != null) {
                throw new BusinessError("INPUT_INVALID", 422, "申辩不能引用问询标识");
            }
            if (!facts.decided()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项尚未决定");
            }
            var eligibility = store.appealEligibility(facts.caseId(), actor)
                    .orElseThrow(() -> new BusinessError("ACTION_NOT_ALLOWED", 403, "当前账户无申辩资格"));
            Instant now = now();
            if (now.isAfter(eligibility.appealDeadlineAt())) {
                throw new BusinessError("CASE_APPEAL_WINDOW_ENDED", 409, "申辩期已结束");
            }
            if (store.hasPendingAppeal(facts.caseId(), actor)) {
                throw new BusinessError("STATE_CONFLICT", 409, "上一条申辩仍待处理");
            }
            long conversationId = requireThread(facts.caseId(), actor, message.conversationId());
            var appended = threads.append(transaction, facts.caseId(), actor, CaseVocabulary.KIND_APPEAL,
                    CaseVocabulary.ACTOR_ACCOUNT, actor, message.body());
            long actionId = store.addAction(new CaseRecords.Action(0, facts.caseId(),
                    CaseVocabulary.ACTION_APPEAL, CaseVocabulary.ACTOR_ACCOUNT, actor, now,
                    appended.messageId(), actor, null, null, null, null, null));
            store.touch(facts.caseId(), now);
            audit(transaction, "case.appeal", facts.caseId(), actor);
            return messageResponse(facts, conversationId, appended, actionId, CaseVocabulary.KIND_APPEAL);
        }

        private WriteResult.Response<?> managerReply(WriteTransaction transaction, CaseRecords.Facts facts,
                                                     long actor, CaseCommands.Message message, LockPlan plan) {
            if (!facts.claimedBy(actor)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (message.inquiryActionId() != null) {
                throw new BusinessError("INPUT_INVALID", 422, "处理申辩不能引用问询标识");
            }
            if (message.appealActionId() == null) {
                throw new BusinessError("INPUT_INVALID", 422, "回复申辩须给出申辩标识");
            }
            if (message.resolution() == null || !CaseVocabulary.RESOLUTIONS.contains(message.resolution())) {
                throw new BusinessError("INPUT_INVALID", 422, "处理结果取值无效");
            }
            boolean uphold = CaseVocabulary.RESOLUTION_UPHOLD.equals(message.resolution());
            if (uphold) {
                rejectSelectionFields(message);
            } else {
                if (message.originalEnforcementId() == null) {
                    throw new BusinessError("INPUT_INVALID", 422, "撤销或调整须选择原处置");
                }
                if (CaseVocabulary.RESOLUTION_ADJUST.equals(message.resolution())) {
                    if (message.replacementEnforcements().isEmpty()) {
                        throw new BusinessError("INPUT_INVALID", 422, "调整处置须给出替代处置");
                    }
                } else if (!message.replacementEnforcements().isEmpty()) {
                    throw new BusinessError("INPUT_INVALID", 422, "撤销处置不能同时给出替代处置");
                }
            }
            var appeal = store.action(facts.caseId(), message.appealActionId())
                    .filter(action -> CaseVocabulary.ACTION_APPEAL.equals(action.actionKind()))
                    .orElseThrow(() -> new BusinessError("INPUT_INVALID", 422, "申辩不存在"));
            if (store.appealResolved(facts.caseId(), appeal.actionId())) {
                throw new BusinessError("STATE_CONFLICT", 409, "申辩已处理");
            }
            if (appeal.relatedAccountId() == null) {
                throw new BusinessError("STATE_CONFLICT", 409, "申辩记录不完整");
            }
            var basisRefs = message.basisRefs();
            String basisRef;
            if (basisRefs.isEmpty()) {
                if (message.basisRef() == null || message.basisRef().isBlank()) {
                    throw new BusinessError("BASIS_REQUIRED", 422, "处理申辩须给出依据");
                }
                basisRef = requiredText(message.basisRef(), settings.getMaxNoteLength(), "依据引用");
                basisRefs = List.of(basisRef);
            } else {
                if (message.basisRef() != null) {
                    throw new BusinessError("INPUT_INVALID", 422, "只能使用一种依据引用字段");
                }
                var allowed = decisionBasisRefs(facts.caseId());
                allowed.add("action:" + appeal.actionId());
                if (!allowed.containsAll(basisRefs)) {
                    throw new BusinessError("BASIS_REQUIRED", 422, "请选择本事项的依据");
                }
                basisRefs = basisRefs.stream().distinct().toList();
                basisRef = basisJson(basisRefs);
            }
            long appellant = appeal.relatedAccountId();
            long conversationId = requireThread(facts.caseId(), appellant, message.conversationId());
            Instant now = now();
            String sourceNote = uphold ? null : reverse(transaction, facts, appellant, message, actor, now, plan,
                    basisRef, basisRefs);
            var appended = threads.append(transaction, facts.caseId(), appellant,
                    CaseVocabulary.KIND_MANAGER_REPLY, CaseVocabulary.ACTOR_MANAGER, actor, message.body());
            long actionId = store.addAction(new CaseRecords.Action(0, facts.caseId(),
                    CaseVocabulary.ACTION_MANAGER_REPLY, CaseVocabulary.ACTOR_MANAGER, actor, now,
                    appended.messageId(), appellant, null, appeal.actionId(), message.resolution(),
                    sourceNote, basisJson(basisRefs)));
            store.touch(facts.caseId(), now);
            audit(transaction, "case.appeal.resolve", facts.caseId(), actor);
            archiveIfFullyReverted(transaction, facts, actor, now);
            return messageResponse(facts, conversationId, appended, actionId, CaseVocabulary.KIND_MANAGER_REPLY);
        }

        /**
         * Applies the manager-selected original enforcement exactly once. A revoke only compensates
         * the original. An adjust first compensates it and then applies the concrete replacement in
         * the same transaction; if either step fails the transaction rolls back the subject state,
         * the case facts and every notification. The adapter owns the subject lock callbacks and
         * resolves the original target from the persisted case link, never from client input.
         */
        private String reverse(WriteTransaction transaction, CaseRecords.Facts facts, long appellant,
                               CaseCommands.Message message, long manager, Instant now, LockPlan plan,
                               String basisRef, List<String> basisRefs) {
            if (enforcement == null) {
                throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "撤销或调整须由处置执行提供");
            }
            var recorded = selectedEnforcement(facts.caseId(), message.originalEnforcementId(), appellant, true);
            boolean adjust = CaseVocabulary.RESOLUTION_ADJUST.equals(message.resolution());
            var replacements = adjust
                    ? replacementInstructions(message, recorded)
                    : List.<CaseRecords.EnforcementInstruction>of();
            if (replacements.stream().anyMatch(item -> recorded.action().equals(item.action()))) {
                throw new BusinessError("INPUT_INVALID", 422, "调整处置须给出新的处置动作");
            }
            var callbacks = enforcement.reverseLockCallbacks(transaction.context(), facts.caseId(), recorded,
                    message.resolution());
            if (!replacements.isEmpty()) {
                callbacks = callbacks.merge(enforcement.lockCallbacks(transaction.context(), facts.caseId(),
                        replacements));
            }
            var missing = callbacks.missingFrom(plan);
            if (!missing.accounts().isEmpty() || !missing.resources().isEmpty()) {
                throw new LockPlan.Changed(missing);
            }
            String executionBasis = "case:" + facts.caseId();
            var reversed = enforcement.reverse(transaction, transaction.context(), facts.caseId(), recorded,
                    message.resolution(), executionBasis, basisRef, now);
            if (reversed.isEmpty()) {
                throw new BusinessError("STATE_CONFLICT", 409, "原处置未产生补偿记录");
            }
            recordOutcomes(transaction, facts, reversed, manager, basisRef, now, ":reversed");
            if (adjust) {
                var adjusted = enforcement.execute(transaction, transaction.context(), facts.caseId(), basisRef,
                        executionBasis, replacements, now);
                if (adjusted.isEmpty()) {
                    throw new BusinessError("STATE_CONFLICT", 409, "调整处置未产生替代执行记录");
                }
                recordOutcomes(transaction, facts, adjusted, manager, basisRef, now, ":adjusted",
                        replacementBasis(facts.caseId(), message.appealActionId()));
            }
            String sourceNote = "original_enforcement_id=" + recorded.enforcementId();
            if (!replacements.isEmpty()) {
                sourceNote += ";replacement_enforcement_ids=" + replacements.stream()
                        .map(CaseRecords.EnforcementInstruction::enforcementId)
                        .collect(Collectors.joining(","));
            }
            store.markEnforcementLifted(facts.caseId(), recorded.enforcementId(), manager, basisRef, now);
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_LIFT,
                    CaseVocabulary.ACTOR_MANAGER, manager, now, null, appellant, null, null, null,
                    sourceNote, basisJson(basisRefs)));
            return sourceNote;
        }

        private WriteResult.Response<?> messageResponse(CaseRecords.Facts facts, long conversationId,
                                                        CaseRecords.ThreadMessage message, long actionId,
                                                        String messageKind) {
            var body = json.createObjectNode();
            body.put("case_action_id", Long.toString(actionId));
            body.put("case_message_id", Long.toString(message.messageId()));
            body.put("seq", message.seq());
            body.put("message_kind", messageKind);
            body.put("created_at", message.createdAt().toString());
            body.set("thread", thread(conversationId));
            return new WriteResult.Response<>(201, body, new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ decision and execution

    private final class DecisionUseCase implements WriteExecutor.UseCase<DecisionRequest, DecisionRequest> {
        @Override
        public JsonNode digestInput(DecisionRequest request) {
            return digest(request.caseId(), request.decision());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, DecisionRequest request) {
            var facts = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
            var plan = new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(facts.caseId())));
            if (!facts.claimedBy(actor(context))) {
                return plan;
            }
            var instructions = instructions(request.decision());
            if (!instructions.isEmpty() && enforcement != null) {
                plan = plan.merge(enforcement.plan(context, facts.caseId(), instructions));
            }
            var accounts = new TreeMap<Long, LockPlan.AccountMode>();
            for (long accountId : targets.relatedAccountIds(facts)) {
                accounts.put(accountId, LockPlan.AccountMode.SHARED);
            }
            return plan.merge(new LockPlan(accounts, Set.of()));
        }

        @Override
        public DecisionRequest qualify(ExecutionContext context, DecisionRequest request, LockPlan plan) {
            managers.requireManagerForWrite(context);
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, DecisionRequest qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, DecisionRequest request,
                                             DecisionRequest qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var snapshot = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
            if (!snapshot.claimedBy(manager)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            var decision = request.decision();
            var instructions = instructions(decision);
            // A decision with subjects locks the actual product/trade rows before the case row.
            // The prepared plan is re-checked here so a target set that grew after prepare is
            // retried by the shared executor instead of widening locks inside the case lock.
            CaseRecords.Facts facts;
            if (instructions.isEmpty()) {
                facts = store.lock(transaction, request.caseId());
            } else {
                if (enforcement == null) {
                    throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "处置执行暂不可用");
                }
                facts = acquireSubjectLocks(transaction, plan,
                        enforcement.lockCallbacks(transaction.context(), request.caseId(), instructions),
                        request.caseId());
            }
            requireLifecycle(facts);
            if (!facts.claimedBy(manager)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            if (facts.decided()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项已决定");
            }
            requireTradeTargets(facts, instructions);
            if (decision.decisionKind() == null || !CaseVocabulary.DECISION_KINDS.contains(decision.decisionKind())) {
                throw new BusinessError("INPUT_INVALID", 422, "decision_kind 取值无效");
            }
            String reason = requiredText(decision.reason(), settings.getMaxReasonLength(), "决定理由");
            if (!decision.basisRefs().isEmpty() && !decisionBasisRefs(facts.caseId()).containsAll(decision.basisRefs())) {
                throw new BusinessError("BASIS_REQUIRED", 422, "请选择本事项的问询、回复或用户补充材料");
            }
            Instant now = now();
            if (instructions.isEmpty()) {
                facts = store.decide(facts.caseId(), decision.decisionKind(), reason, manager, now);
            } else if (!store.decideIfClaimed(facts.caseId(), decision.decisionKind(), reason, manager, now)) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项已由其他管理员处理");
            }
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_DECIDE,
                    CaseVocabulary.ACTOR_MANAGER, manager, now, null, null, null, null, null, null,
                    basisJson(decision.basisRefs())));
            var outcomes = enforce(transaction, facts, instructions, manager, reason, now);
            if (!instructions.isEmpty()) {
                facts = store.require(facts.caseId());
            }
            var notified = new TreeSet<Long>();
            for (var outcome : outcomes) {
                notified.addAll(outcome.affectedAccountIds());
            }
            store.touch(facts.caseId(), now);
            audit(transaction, "case.decide", facts.caseId(), manager);
            var body = json.createObjectNode();
            body.put("case_id", Long.toString(facts.caseId()));
            body.put("decision_kind", facts.decisionKind());
            body.put("decided_at", facts.decidedAt().toString());
            body.put("case_status", facts.caseStatus());
            var enforcementArray = body.putArray("enforcements");
            for (var persisted : store.enforcements(facts.caseId())) {
                var item = enforcementArray.addObject();
                item.put("enforcement_id", persisted.enforcementId());
                item.put("action", persisted.action());
                item.put("target_ref", persisted.targetType() + ":" + persisted.targetId());
                item.put("result_ref", persisted.resultType() == null ? null
                        : persisted.resultType() + ":" + persisted.resultId());
                item.put("result_status", persisted.resultStatus());
                item.put("previous_state", persisted.previousState());
                item.put("current_state", persisted.currentState());
                var scope = item.putArray("affected_scope");
                var scopeRefs = new LinkedHashSet<ResourceRef>();
                scopeRefs.add(new ResourceRef(persisted.targetType(), persisted.targetId()));
                persisted.affectedAccountIds().forEach(id -> scopeRefs.add(new ResourceRef("account", id)));
                for (var ref : scopeRefs) {
                    var entry = scope.addObject();
                    entry.put("resource_type", ref.type());
                    entry.put("resource_id", Long.toString(ref.id()));
                }
            }
            var notifiedArray = body.putArray("notified_account_ids");
            notified.forEach(id -> notifiedArray.add(Long.toString(id)));
            return new WriteResult.Response<>(201, body, new ResourceRef("case", facts.caseId()));
        }

        private List<CaseRecords.EnforcementOutcome> enforce(WriteTransaction transaction, CaseRecords.Facts facts,
                                                            List<CaseRecords.EnforcementInstruction> instructions,
                                                            long manager, String reason, Instant now) {
            if (instructions.isEmpty()) {
                return List.of();
            }
            if (enforcement == null) {
                throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "处置执行暂不可用");
            }
            String basisRef = "case:" + facts.caseId();
            var outcomes = enforcement.execute(transaction, transaction.context(), facts.caseId(), reason,
                    basisRef, instructions, now);
            var seen = new TreeSet<Long>();
            for (var outcome : outcomes) {
                store.addEnforcement(new CaseRecords.Enforcement(outcome.enforcementId(), facts.caseId(),
                        outcome.action(), outcome.targetType(), outcome.targetId(), basisRef, manager, now,
                        outcome.resultType(), outcome.resultId(), outcome.resultStatus(), outcome.previousState(),
                        outcome.currentState(), outcome.affectedAccountIds(), null, null, now, null));
                notificationFor(transaction, facts, outcome, reason, now);
                for (long accountId : outcome.affectedAccountIds()) {
                    if (!seen.add(accountId)) {
                        continue;
                    }
                    if (store.appealEligibility(facts.caseId(), accountId).isEmpty()) {
                        store.addAppealEligibility(facts.caseId(), accountId,
                                now.plusSeconds(settings.getAppealWindowSeconds()), basisRef, now);
                    }
                    threadWithNotice(transaction, facts.caseId(), accountId);
                }
            }
            return outcomes;
        }

        private void notificationFor(WriteTransaction transaction, CaseRecords.Facts facts,
                                     CaseRecords.EnforcementOutcome outcome, String reason, Instant now) {
            if (outcome.affectedAccountIds().isEmpty()) {
                return;
            }
            // The trade-owned restore publishes exactly one trade.restored notice per participant.
            // The case entry must not add a second notice for the same restoration.
            if (tradeRestored(outcome)) {
                return;
            }
            String event = enforcementEvent(outcome.action());
            notifications.create(transaction, event,
                    "case:" + facts.caseId() + ":" + outcome.enforcementId() + ":"
                            + notificationSuffix(outcome.action()),
                    new ResourceRef("case", facts.caseId()), Set.copyOf(outcome.affectedAccountIds()),
                    Map.of("case_id", Long.toString(facts.caseId()), "reason", reason), now);
        }

        private void threadWithNotice(WriteTransaction transaction, long caseId, long accountId) {
            threads.ensure(transaction, caseId, accountId);
            threads.append(transaction, caseId, accountId, CaseVocabulary.KIND_SYSTEM_NOTICE,
                    CaseVocabulary.ACTOR_SYSTEM, 0, "事项已处置，可在本线程查看处理结果并提交申辩。");
        }
    }

    // ------------------------------------------------------------------ close

    private void addCaseThreadLocks(long caseId, Set<LockPlan.Key> resources) {
        for (long accountId : store.relatedAccountIds(caseId)) {
            threads.findConversation(caseId, accountId)
                    .ifPresent(id -> resources.add(new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION,
                            List.of(id))));
        }
    }

    private CaseRecords.Facts archiveCase(WriteTransaction transaction, CaseRecords.Facts facts,
                                         Long manager, Instant now) {
        for (long accountId : store.relatedAccountIds(facts.caseId())) {
            threads.archive(transaction, facts.caseId(), accountId);
        }
        var archived = store.archive(facts.caseId(), now);
        store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_CLOSE,
                manager == null ? CaseVocabulary.ACTOR_SYSTEM : CaseVocabulary.ACTOR_MANAGER,
                manager, now, null, null, null, null, null, null, null));
        return archived;
    }

    private void archiveIfFullyReverted(WriteTransaction transaction, CaseRecords.Facts facts, long manager,
                                        Instant now) {
        if (!facts.decided() || facts.archived() || store.latestPendingAppeal(facts.caseId()).isPresent()) {
            return;
        }
        var applied = store.enforcements(facts.caseId()).stream()
                .filter(item -> "applied".equals(item.resultStatus()) || "replayed".equals(item.resultStatus()))
                .filter(item -> !LIFT_ACTIONS.contains(item.action())).toList();
        if (!applied.isEmpty() && applied.stream().allMatch(item -> item.liftedAt() != null)) {
            archiveCase(transaction, facts, null, now);
            audit(transaction, "case.close", facts.caseId(), manager);
        }
    }

    private final class CloseUseCase implements WriteExecutor.UseCase<CloseRequest, CloseRequest> {
        @Override
        public JsonNode digestInput(CloseRequest request) {
            return json.createObjectNode().put("case_id", request.caseId());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, CloseRequest request) {
            var facts = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
            var resources = new TreeSet<LockPlan.Key>();
            resources.add(CaseLifecycleStore.lockKey(facts.caseId()));
            addCaseThreadLocks(facts.caseId(), resources);
            return new LockPlan(Map.of(), resources);
        }

        @Override
        public CloseRequest qualify(ExecutionContext context, CloseRequest request, LockPlan plan) {
            managers.requireManagerForWrite(context);
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, CloseRequest qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, CloseRequest request,
                                             CloseRequest qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (!facts.claimedBy(manager)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (facts.archived()) {
                return new WriteResult.Response<>(200, closed(facts), new ResourceRef("case", facts.caseId()));
            }
            if (!facts.decided()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项尚未决定");
            }
            Instant now = now();
            for (var eligibility : store.appealEligibilities(facts.caseId())) {
                if (now.isBefore(eligibility.appealDeadlineAt())) {
                    throw new BusinessError("CASE_APPEAL_WINDOW_OPEN", 409, "申辩期尚未结束");
                }
            }
            if (store.latestPendingAppeal(facts.caseId()).isPresent()) {
                throw new BusinessError("CASE_APPEAL_PENDING", 409, "存在未处理的申辩");
            }
            facts = archiveCase(transaction, facts, manager, now);
            audit(transaction, "case.close", facts.caseId(), manager);
            return new WriteResult.Response<>(200, closed(facts), new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ publication

    private final class PublishUseCase implements WriteExecutor.UseCase<PublishRequest, PublishRequest> {
        @Override
        public JsonNode digestInput(PublishRequest request) {
            return digest(request.caseId(), request.publish());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, PublishRequest request) {
            return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())));
        }

        @Override
        public PublishRequest qualify(ExecutionContext context, PublishRequest request, LockPlan plan) {
            managers.requireManagerForWrite(context);
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, PublishRequest qualification,
                                       ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, PublishRequest request,
                                             PublishRequest qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (!facts.claimedBy(manager)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (!facts.archived()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项尚未结案");
            }
            if (facts.publicResultAt() != null) {
                throw new BusinessError("STATE_CONFLICT", 409, "结果已公开");
            }
            if (!CaseVocabulary.REPORT.equals(facts.caseType())) {
                throw new BusinessError("STATE_CONFLICT", 409, "仅举报事项可公开结果");
            }
            String summary = requiredText(request.publish().summary(), settings.getMaxReasonLength(), "公开结论");
            String reason = requiredText(request.publish().reason(), settings.getMaxNoteLength(), "公开原因");
            Instant now = now();
            facts = store.publish(facts.caseId(), summary, reason, manager, now);
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_PUBLISH_RESULT,
                    CaseVocabulary.ACTOR_MANAGER, manager, now, null, null, null, null, null, null, null));
            if (facts.reporterAccountId() != null) {
                notifications.create(transaction, CaseVocabulary.EVENT_RESULT_PUBLISHED,
                        "case:" + facts.caseId() + ":result_published",
                        new ResourceRef("case", facts.caseId()), Set.of(facts.reporterAccountId()),
                        Map.of("case_id", Long.toString(facts.caseId())), now);
            }
            audit(transaction, "case.publish_result", facts.caseId(), manager);
            var body = json.createObjectNode();
            body.put("case_id", Long.toString(facts.caseId()));
            body.put("public_result_at", facts.publicResultAt().toString());
            return new WriteResult.Response<>(200, body, new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ lift

    private final class LiftUseCase implements WriteExecutor.UseCase<LiftRequest, LiftRequest> {
        @Override
        public JsonNode digestInput(LiftRequest request) {
            var node = json.createObjectNode();
            node.put("case_id", request.caseId());
            node.put("enforcement_id", request.enforcementId());
            node.put("reason", request.reason());
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, LiftRequest request) {
            var facts = store.find(request.caseId()).orElseThrow(CaseApplication::notVisible);
            var recorded = requireRecorded(request.caseId(), request.enforcementId());
            var resources = new TreeSet<LockPlan.Key>();
            resources.add(CaseLifecycleStore.lockKey(facts.caseId()));
            addCaseThreadLocks(facts.caseId(), resources);
            var accounts = new TreeMap<Long, LockPlan.AccountMode>();
            for (long accountId : targets.relatedAccountIds(facts)) {
                accounts.put(accountId, LockPlan.AccountMode.SHARED);
            }
            var plan = new LockPlan(accounts, resources);
            if (enforcement != null) {
                plan = plan.merge(enforcement.reversePlan(context, facts.caseId(), recorded, "revoke"));
            }
            return plan;
        }

        @Override
        public LiftRequest qualify(ExecutionContext context, LiftRequest request, LockPlan plan) {
            managers.requireManagerForWrite(context);
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, LiftRequest qualification, ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, LiftRequest request,
                                             LiftRequest qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var recordedBefore = requireRecorded(request.caseId(), request.enforcementId());
            var subjects = enforcement == null ? SubjectPlan.empty()
                    : enforcement.reverseLockCallbacks(transaction.context(), request.caseId(), recordedBefore,
                    "revoke");
            var facts = acquireSubjectLocks(transaction, plan, subjects, request.caseId());
            requireLifecycle(facts);
            if (!facts.claimedBy(manager)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            String reason = requiredText(request.reason(), settings.getMaxNoteLength(), "解除原因");
            var recorded = requireRecorded(facts.caseId(), request.enforcementId());
            requireRecordedTarget(facts, recorded);
            var existing = store.lift(facts.caseId(), request.enforcementId());
            if (existing.isPresent()) {
                return lifted(recorded, existing.get(), List.of());
            }
            if (!"applied".equals(recorded.resultStatus())) {
                throw new BusinessError("RESTRICTION_NOT_ACTIVE", 409, "执行记录不在生效状态");
            }
            if (enforcement == null) {
                throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "解除须由处置执行提供");
            }
            Instant now = now();
            String basisRef = "case:" + facts.caseId();
            var outcomes = enforcement.reverse(transaction, transaction.context(), facts.caseId(), recorded,
                    "revoke", basisRef, reason, now);
            recordReversal(transaction, facts, outcomes, manager, reason, now);
            store.markEnforcementLifted(facts.caseId(), request.enforcementId(), manager, reason, now);
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_LIFT,
                    CaseVocabulary.ACTOR_MANAGER, manager, now, null, null, null, null, null, reason,
                    basisJson(List.of(reason))));
            store.touch(facts.caseId(), now);
            audit(transaction, "case.enforcement.lift", facts.caseId(), manager);
            archiveIfFullyReverted(transaction, facts, manager, now);
            var lifted = store.lift(facts.caseId(), request.enforcementId())
                    .orElse(new CaseRecords.Lift(now, manager));
            return lifted(recorded, lifted, outcomes);
        }

        private WriteResult.Response<?> lifted(CaseRecords.Enforcement recorded, CaseRecords.Lift lift,
                                               List<CaseRecords.EnforcementOutcome> outcomes) {
            var body = json.createObjectNode();
            body.put("enforcement_id", recorded.enforcementId());
            body.put("lifted_at", lift.liftedAt().toString());
            body.put("lifted_by", Long.toString(lift.liftedBy()));
            var scope = body.putArray("restored_scope");
            var seen = new TreeSet<Long>();
            var remaining = new TreeSet<String>();
            for (var outcome : outcomes) {
                for (long accountId : outcome.affectedAccountIds()) {
                    if (seen.add(accountId)) {
                        scope.add("account:" + accountId);
                    }
                }
                remaining.addAll(outcome.remainingRestrictions());
            }
            var remainingArray = body.putArray("remaining_restrictions");
            remaining.forEach(remainingArray::add);
            return new WriteResult.Response<>(200, body, new ResourceRef("case", recorded.caseId()));
        }
    }

    // ------------------------------------------------------------------ platform record evidence

    private final class EvidenceReferenceUseCase
            implements WriteExecutor.UseCase<EvidenceReferenceRequest, EvidenceReferenceRequest> {
        @Override
        public JsonNode digestInput(EvidenceReferenceRequest request) {
            return digest(request.caseId(), request.reference());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, EvidenceReferenceRequest request) {
            return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())));
        }

        @Override
        public EvidenceReferenceRequest qualify(ExecutionContext context, EvidenceReferenceRequest request,
                                                LockPlan plan) {
            requireEvidenceManager(context);
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, EvidenceReferenceRequest qualification,
                                        ResourceRef resource) {
            if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
                throw notVisible();
            }
            var facts = store.find(resource.id()).orElseThrow(CaseApplication::notVisible);
            if (!facts.claimedBy(actor(context))) {
                throw notVisible();
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, EvidenceReferenceRequest request,
                                             EvidenceReferenceRequest qualification, LockPlan plan) {
            long manager = actor(transaction.context());
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (!facts.claimedBy(manager)) {
                throw notVisible();
            }
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            var reference = request.reference();
            targets.requireReportedMessage(facts, reference.conversationKind(), reference.conversationId(),
                    reference.messageId());
            String scope = CaseRecords.MessageScope.format(reference.conversationKind(),
                    reference.conversationId());
            var existing = store.platformEvidence(facts.caseId(), CaseVocabulary.SOURCE_MESSAGE,
                    reference.messageId(), scope);
            if (existing.isPresent()) {
                return new WriteResult.Response<>(200, evidenceReference(facts.caseId(),
                        existing.get().evidenceId(), reference.messageId(), true),
                        new ResourceRef("case", facts.caseId()));
            }
            long evidenceId = store.addPlatformEvidence(facts.caseId(), CaseVocabulary.SOURCE_MESSAGE,
                    reference.messageId(), scope, manager, now());
            audit(transaction, "case.evidence.reference", facts.caseId(), manager);
            return new WriteResult.Response<>(201, evidenceReference(facts.caseId(), evidenceId,
                    reference.messageId(), false), new ResourceRef("case", facts.caseId()));
        }
    }

    // ------------------------------------------------------------------ helpers

    private JsonNode evidenceReference(long caseId, long evidenceId, long messageId, boolean reused) {
        var body = json.createObjectNode();
        body.put("evidence_id", Long.toString(evidenceId));
        body.put("case_id", Long.toString(caseId));
        body.put("evidence_kind", CaseVocabulary.EVIDENCE_PLATFORM_RECORD);
        var source = body.putObject("source_ref");
        source.put("resource_type", CaseVocabulary.SOURCE_MESSAGE);
        source.put("resource_id", Long.toString(messageId));
        body.put("reused", reused);
        return body;
    }

    /** Role failures stay hidden as 404 because this route only exists for the fixed claimant. */
    private void requireEvidenceManager(ExecutionContext context) {
        actor(context);
        try {
            managers.requireManagerForWrite(context);
        } catch (BusinessError denied) {
            throw notVisible();
        }
    }

    /**
     * Acquires the actual subject rows and the already planned case row once, in the public key
     * order. The subject callbacks only lock rows; the case callback re-reads the case row with
     * {@code FOR UPDATE} without declaring a nested transaction lock. Keys beyond the prepared
     * plan propagate {@link LockPlan.Changed} so the executor rolls back and re-plans the whole
     * write instead of locking a lower level after a higher one.
     */
    private CaseRecords.Facts acquireSubjectLocks(WriteTransaction transaction, LockPlan prepared,
                                                  SubjectPlan subjects, long caseId) {
        var holder = new AtomicReference<CaseRecords.Facts>();
        var withCase = subjects.merge(SubjectPlan.resource(CaseLifecycleStore.lockKey(caseId),
                tx -> holder.set(store.requireLocked(tx, caseId))));
        var missing = withCase.missingFrom(prepared);
        if (!missing.accounts().isEmpty() || !missing.resources().isEmpty()) {
            throw new LockPlan.Changed(missing);
        }
        withCase.acquire(transaction);
        return holder.get();
    }

    /** A subject execution may only target the trade recorded as this case's target. */
    private static void requireTradeTargets(CaseRecords.Facts facts,
                                            List<CaseRecords.EnforcementInstruction> instructions) {
        for (var item : instructions) {
            if (!TRADE_ACTIONS.contains(item.action())) {
                continue;
            }
            if (!"trade".equals(facts.targetType()) || facts.targetId() == null
                    || facts.targetId() != item.targetId()) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项目标与交易不一致");
            }
        }
    }

    /** A recorded trade enforcement must still point at this case's current target trade. */
    private static void requireRecordedTarget(CaseRecords.Facts facts, CaseRecords.Enforcement recorded) {
        if (!"trade".equals(recorded.targetType())) {
            return;
        }
        if (!"trade".equals(facts.targetType()) || facts.targetId() == null
                || facts.targetId() != recorded.targetId()) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项与执行记录的目标不一致");
        }
    }

    private JsonNode digest(long caseId, Object input) {
        var node = json.createObjectNode();
        node.put("case_id", caseId);
        node.set("input", json.valueToTree(input));
        return node;
    }

    private static String enforcementEvent(String action) {
        return switch (action) {
            case "remove_content" -> CaseVocabulary.EVENT_CONTENT_REMOVED;
            case "remove_evaluation_content" -> CaseVocabulary.EVENT_EVALUATION_REMOVED;
            case "freeze_trade" -> CaseVocabulary.EVENT_TRADE_FROZEN;
            case "lift_trade_freeze" -> CaseVocabulary.EVENT_TRADE_UNFROZEN;
            case "adjust_trade_status" -> CaseVocabulary.EVENT_TRADE_ADJUSTED;
            default -> CaseVocabulary.EVENT_DECIDED;
        };
    }

    /**
     * Shared resolution of the manager-selected original execution. The prepare phase calls it
     * read-only to bind the same case and appellant subject rows; the write phase calls it after
     * the case lock with {@code requireEligible=true} to re-check the mutable active/applied and
     * unlifted facts. A mismatched case, appellant or record is hidden as a scoped 404.
     */
    private CaseRecords.Enforcement selectedEnforcement(long caseId, String enforcementId, Long appellant,
                                                        boolean requireEligible) {
        if (enforcementId == null || enforcementId.isBlank()) {
            if (requireEligible) {
                throw new BusinessError("INPUT_INVALID", 422, "撤销或调整须选择原处置");
            }
            return null;
        }
        if (enforcementId.length() > 128) {
            throw new BusinessError("INPUT_INVALID", 422, "原处置标识无效");
        }
        var recorded = store.enforcement(caseId, enforcementId).orElse(null);
        // The store lookup is already scoped by case, but the selected record must still prove
        // its case and appellant linkage before it can be reversed.
        boolean sameCase = recorded != null && recorded.caseId() == caseId;
        boolean affected = sameCase && appellant != null
                && recorded.affectedAccountIds().contains(appellant);
        if (!sameCase || (appellant != null && !affected)) {
            if (requireEligible) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "执行记录不存在");
            }
            return null;
        }
        if (requireEligible) {
            if (!affected) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "执行记录不存在");
            }
            if (!"applied".equals(recorded.resultStatus())
                    || store.lift(caseId, enforcementId).isPresent()) {
                throw new BusinessError("STATE_CONFLICT", 409, "原处置已不再生效");
            }
            if (LIFT_ACTIONS.contains(recorded.action()) || replacementSource(recorded)) {
                throw new BusinessError("STATE_CONFLICT", 409, "所选记录不是原始处置");
            }
            if (TERMINAL_ACTIONS.contains(recorded.action())
                    && (recorded.currentState() == null || !recorded.currentState().startsWith("status=in_progress"))) {
                throw new BusinessError("TRADE_TERMINAL", 409, "已结束交易保持终态，不能撤销或调整");
            }
            if (!REVERSIBLE_ACTIONS.contains(recorded.action())) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "该处置不可撤销或调整");
            }
        }
        return recorded;
    }

    private static void rejectSelectionFields(CaseCommands.Message message) {
        if (message.originalEnforcementId() != null || !message.replacementEnforcements().isEmpty()) {
            throw new BusinessError("INPUT_INVALID", 422, "当前回复不能给出原处置或替代处置");
        }
    }

    private static String notificationSuffix(String action) {
        return switch (action) {
            case "remove_content" -> "removed";
            case "remove_evaluation_content" -> "evaluated";
            default -> "affected";
        };
    }

    private static void rejectResolutionFields(CaseCommands.Message message) {
        rejectSelectionFields(message);
        if (message.appealActionId() != null || message.resolution() != null || !message.basisRefs().isEmpty()) {
            throw new BusinessError("INPUT_INVALID", 422, "当前发言不能给出申辩处理字段");
        }
    }

    /** T2-29: adjust_trade_status from abnormal to in_progress; its trade notification is enough. */
    private static boolean tradeRestored(CaseRecords.EnforcementOutcome outcome) {
        return "adjust_trade_status".equals(outcome.action())
                && outcome.previousState() != null
                && outcome.previousState().startsWith("status=abnormal")
                && outcome.currentState() != null
                && outcome.currentState().startsWith("status=in_progress");
    }

    /**
     * A replacement must stay on the original target and name a new concrete action. This keeps
     * an adjustment from becoming an arbitrary account/product/trade selection or a hidden lift.
     */
    private List<CaseRecords.EnforcementInstruction> replacementInstructions(CaseCommands.Message message,
                                                                              CaseRecords.Enforcement recorded) {
        var replacements = instructions(message.replacementEnforcements());
        for (var item : replacements) {
            if (!recorded.targetType().equals(item.targetType()) || recorded.targetId() != item.targetId()) {
                throw new BusinessError("INPUT_INVALID", 422, "调整处置须沿用原处置目标");
            }
            if (LIFT_ACTIONS.contains(item.action())) {
                throw new BusinessError("INPUT_INVALID", 422, "调整处置须给出新的处置动作");
            }
        }
        return replacements;
    }

    private static String replacementBasis(long caseId, Long appealActionId) {
        return "case:" + caseId + ":appeal:" + appealActionId + ":replacement";
    }

    private static boolean replacementSource(CaseRecords.Enforcement recorded) {
        return recorded.basisRef() != null && recorded.basisRef().contains(":replacement");
    }

    private Long appellantFor(long caseId, Long appealActionId) {
        if (appealActionId == null) {
            return null;
        }
        return store.action(caseId, appealActionId)
                .filter(action -> CaseVocabulary.ACTION_APPEAL.equals(action.actionKind()))
                .map(CaseRecords.Action::relatedAccountId)
                .orElse(null);
    }

    private static boolean reversal(CaseCommands.Message message) {
        return CaseVocabulary.KIND_MANAGER_REPLY.equals(message.messageKind())
                && message.resolution() != null
                && !CaseVocabulary.RESOLUTION_UPHOLD.equals(message.resolution());
    }

    private CaseRecords.Enforcement requireRecorded(long caseId, String enforcementId) {
        if (enforcementId == null || enforcementId.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "enforcement_id 不能为空");
        }
        return store.enforcement(caseId, enforcementId)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "执行记录不存在"));
    }

    /** Persists compensating enforcement links and notifies their affected accounts. */
    private void recordReversal(WriteTransaction transaction, CaseRecords.Facts facts,
                                List<CaseRecords.EnforcementOutcome> outcomes, long manager, String reason,
                                Instant now) {
        recordOutcomes(transaction, facts, outcomes, manager, reason, now, ":reversed");
    }

    private void recordOutcomes(WriteTransaction transaction, CaseRecords.Facts facts,
                                List<CaseRecords.EnforcementOutcome> outcomes, long manager, String reason,
                                Instant now, String suffix) {
        recordOutcomes(transaction, facts, outcomes, manager, reason, now, suffix,
                "case:" + facts.caseId());
    }

    private void recordOutcomes(WriteTransaction transaction, CaseRecords.Facts facts,
                                List<CaseRecords.EnforcementOutcome> outcomes, long manager, String reason,
                                Instant now, String suffix, String basisRef) {
        for (var outcome : outcomes) {
            store.addEnforcement(new CaseRecords.Enforcement(outcome.enforcementId(), facts.caseId(),
                    outcome.action(), outcome.targetType(), outcome.targetId(), basisRef, manager, now,
                    outcome.resultType(), outcome.resultId(), outcome.resultStatus(), outcome.previousState(),
                    outcome.currentState(), outcome.affectedAccountIds(), null, null, now, null));
            if (!outcome.affectedAccountIds().isEmpty() && !tradeRestored(outcome)) {
                notifications.create(transaction, enforcementEvent(outcome.action()),
                        "case:" + facts.caseId() + ":" + outcome.enforcementId() + suffix,
                        new ResourceRef("case", facts.caseId()),
                        Set.copyOf(outcome.affectedAccountIds()),
                        Map.of("case_id", Long.toString(facts.caseId()), "reason", reason == null ? "" : reason),
                        now);
            }
        }
    }

    private static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    private List<CaseRecords.EnforcementInstruction> instructions(CaseCommands.Decision decision) {
        return instructions(decision.enforcements());
    }

    private List<CaseRecords.EnforcementInstruction> instructions(List<CaseCommands.Enforcement> enforcements) {
        var list = new ArrayList<CaseRecords.EnforcementInstruction>();
        for (var item : enforcements) {
            if (item.action() == null || !ENFORCEMENT_ACTIONS.contains(item.action())) {
                throw new BusinessError("INPUT_INVALID", 422, "执行动作无效");
            }
            if (item.targetType() == null || item.targetType().isBlank() || item.targetId() <= 0) {
                throw new BusinessError("TARGET_INVALID", 422, "执行目标无效");
            }
            if (TRADE_ACTIONS.contains(item.action()) && !"trade".equals(item.targetType())) {
                throw new BusinessError("TARGET_INVALID", 422, "交易动作的目标无效");
            }
            String expected = item.expectedResult();
            if ("adjust_trade_status".equals(item.action())) {
                if (expected == null || expected.isBlank()) {
                    throw new BusinessError("INPUT_INVALID", 422, "调整交易状态须给出目标状态");
                }
                expected = expected.trim().toLowerCase(Locale.ROOT);
                if (!ADJUST_TRADE_TARGETS.contains(expected)) {
                    throw new BusinessError("INPUT_INVALID", 422, "调整交易状态的目标无效");
                }
            }
            list.add(new CaseRecords.EnforcementInstruction(UUID.randomUUID().toString(), item.action(),
                    item.targetType(), item.targetId(), expected));
        }
        return list;
    }

    private Long attachEvidence(WriteTransaction transaction, long caseId, long reporter, List<Long> fileIds) {
        if (fileIds.isEmpty()) {
            return null;
        }
        var ordered = fileIds.stream().distinct().sorted().toList();
        var references = files.attach(transaction, caseId, reporter, ordered);
        Instant now = now();
        Long first = null;
        for (int index = 0; index < ordered.size(); index++) {
            Long referenceId = index < references.size() ? references.get(index) : null;
            long evidenceId = store.addEvidence(caseId, ordered.get(index), referenceId, reporter, now);
            if (index == 0) first = evidenceId;
        }
        return first;
    }

    private void lockFiles(WriteTransaction transaction, List<Long> fileIds) {
        if (fileIds.isEmpty()) {
            return;
        }
        for (long fileId : new TreeSet<>(fileIds)) {
            transaction.lock(new LockPlan.Key(LockPlan.Domain.FILE_RECORD, List.of(fileId)),
                    () -> files.lockFile(fileId));
        }
    }

    private LockPlan fileLocks(List<Long> fileIds) {
        var resources = new TreeSet<LockPlan.Key>();
        for (long fileId : fileIds) {
            resources.add(new LockPlan.Key(LockPlan.Domain.FILE_RECORD, List.of(fileId)));
        }
        return new LockPlan(Map.of(), resources);
    }

    private long requireThread(long caseId, long relatedAccountId, Long conversationId) {
        long expected = threads.findConversation(caseId, relatedAccountId)
                .orElseThrow(() -> new BusinessError("PARTICIPANT_REQUIRED", 404, "事项线程不存在"));
        if (conversationId != null && conversationId != expected) {
            throw new BusinessError("PARTICIPANT_REQUIRED", 404, "事项线程不存在");
        }
        return expected;
    }

    private JsonNode submitted(long caseId, String status, boolean reused) {
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(caseId));
        body.put("case_status", status);
        body.put("reused", reused);
        return body;
    }

    private JsonNode thread(long conversationId) {
        var body = json.createObjectNode();
        body.put("conversation_kind", "case");
        body.put("conversation_id", Long.toString(conversationId));
        return body;
    }

    private JsonNode closed(CaseRecords.Facts facts) {
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(facts.caseId()));
        body.put("case_status", facts.caseStatus());
        body.put("archived_at", facts.archivedAt().toString());
        return body;
    }

    private Set<String> decisionBasisRefs(long caseId) {
        var allowed = new java.util.HashSet<String>();
        store.actions(caseId).stream().filter(CaseRecords.Action::decisionBasis)
                .forEach(action -> allowed.add("action:" + action.actionId()));
        store.evidence(caseId).stream().filter(CaseRecords.Evidence::decisionBasis)
                .forEach(evidence -> allowed.add("evidence:" + evidence.evidenceId()));
        return allowed;
    }

    private String basisJson(List<String> basisRefs) {
        var array = json.createArrayNode();
        basisRefs.forEach(array::add);
        return array.toString();
    }

    private void audit(WriteTransaction transaction, String action, long caseId, long actor) {
        var facts = json.createObjectNode();
        facts.put("case_id", caseId);
        facts.put("actor", actor);
        transaction.audit(action, new ResourceRef("case", caseId), new ResourceRef("case", caseId), facts);
    }

    private static void requireLifecycle(CaseRecords.Facts facts) {
        if (!facts.lifecycle()) {
            throw notVisible();
        }
    }

    private Instant now() {
        return clock.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private String requiredText(String value, int maxLength, String field) {
        if (value == null || value.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, field + "不能为空");
        }
        String trimmed = value.trim();
        if (trimmed.length() > maxLength) {
            throw new BusinessError("INPUT_INVALID", 422, field + "超出长度限制");
        }
        return trimmed;
    }

    private String optionalText(String value, int maxLength, String field) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim();
        if (trimmed.length() > maxLength) {
            throw new BusinessError("INPUT_INVALID", 422, field + "超出长度限制");
        }
        return trimmed;
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
    }

    private static BusinessError conflict() {
        return new BusinessError("STATE_CONFLICT", 409, "事项状态已变化，请重试");
    }
}
