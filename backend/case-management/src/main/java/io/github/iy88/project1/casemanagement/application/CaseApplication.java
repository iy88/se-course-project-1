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
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.UUID;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import tools.jackson.databind.JsonNode;
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

    private static final Set<String> ENFORCEMENT_ACTIONS = Set.of(
            "restrict_account", "lift_account_restriction", "withdraw_public_access", "restore_display",
            "remove_content", "freeze_trade", "lift_trade_freeze", "adjust_trade_status",
            "remove_evaluation_content");
    private static final Set<String> TRADE_ACTIONS = Set.of("freeze_trade", "lift_trade_freeze",
            "adjust_trade_status");
    private static final Pattern EVIDENCE_REF = Pattern.compile("(?:evidence:)?(\\d+)");

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

    // ------------------------------------------------------------------ submit and supplement

    private final class SubmitUseCase implements WriteExecutor.UseCase<CaseCommands.Report, CaseCommands.Report> {
        @Override
        public JsonNode digestInput(CaseCommands.Report request) {
            return json.valueToTree(request);
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
                if (facts.archived()) {
                    throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
                }
                store.addAction(new CaseRecords.Action(0, caseId, CaseVocabulary.ACTION_SUPPLEMENT,
                        CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null));
                attachEvidence(transaction, caseId, reporter, request.attachments());
                store.touch(caseId, now);
                audit(transaction, "case.report.supplement", caseId, reporter);
                return new WriteResult.Response<>(200,
                        submitted(caseId, facts.caseStatus(), true), new ResourceRef("case", caseId));
            }
            if (store.findClosedReport(reporter, request.target()).isPresent()) {
                throw new BusinessError("CASE_CLOSED", 409, "同对象举报已结案");
            }
            lockFiles(transaction, request.attachments());
            Long opened = store.openReportIfAbsent(request.target(), reporter, reason, now).orElse(null);
            if (opened == null) {
                var current = store.findOpenReport(reporter, request.target()).orElseThrow(CaseApplication::conflict);
                var facts = store.lock(transaction, current.caseId());
                store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_SUPPLEMENT,
                        CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null));
                attachEvidence(transaction, facts.caseId(), reporter, request.attachments());
                store.touch(facts.caseId(), now);
                audit(transaction, "case.report.supplement", facts.caseId(), reporter);
                return new WriteResult.Response<>(200, submitted(facts.caseId(), facts.caseStatus(), true),
                        new ResourceRef("case", facts.caseId()));
            }
            long caseId = opened;
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
            String note = optionalText(request.supplement().note(), settings.getMaxNoteLength(), "补充说明");
            if (note == null && request.supplement().attachments().isEmpty()) {
                throw new BusinessError("INPUT_INVALID", 422, "补充材料不能为空");
            }
            lockFiles(transaction, request.supplement().attachments());
            Instant now = now();
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_SUPPLEMENT,
                    CaseVocabulary.ACTOR_ACCOUNT, reporter, now, null, null, null, null, null, note, null));
            attachEvidence(transaction, facts.caseId(), reporter, request.supplement().attachments());
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
            return new LockPlan(Map.of(), resources);
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
            var facts = store.lock(transaction, request.caseId());
            requireLifecycle(facts);
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            return switch (message.messageKind()) {
                case CaseVocabulary.KIND_STATEMENT -> statement(transaction, facts, actor, message);
                case CaseVocabulary.KIND_APPEAL -> appeal(transaction, facts, actor, message);
                case CaseVocabulary.KIND_MANAGER_REPLY -> managerReply(transaction, facts, actor, message);
                default -> throw new BusinessError("INPUT_INVALID", 422, "message_kind 取值无效");
            };
        }

        private WriteResult.Response<?> statement(WriteTransaction transaction, CaseRecords.Facts facts,
                                                  long actor, CaseCommands.Message message) {
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
            if (!facts.decided()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项尚未决定");
            }
            var eligibility = store.appealEligibility(facts.caseId(), actor)
                    .orElseThrow(() -> new BusinessError("ACTION_NOT_ALLOWED", 403, "当前账户无申辩资格"));
            Instant now = now();
            if (now.isAfter(eligibility.appealDeadlineAt())) {
                throw new BusinessError("CASE_APPEAL_WINDOW_ENDED", 409, "申辩期已结束");
            }
            if (store.appealOf(facts.caseId(), actor).isPresent()) {
                throw new BusinessError("STATE_CONFLICT", 409, "申辩已提交");
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
                                                     long actor, CaseCommands.Message message) {
            if (!facts.claimedBy(actor)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (message.appealActionId() == null) {
                throw new BusinessError("INPUT_INVALID", 422, "回复申辩须给出申辩标识");
            }
            if (message.resolution() == null || !CaseVocabulary.RESOLUTIONS.contains(message.resolution())) {
                throw new BusinessError("INPUT_INVALID", 422, "处理结果取值无效");
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
            long appellant = appeal.relatedAccountId();
            long conversationId = requireThread(facts.caseId(), appellant, message.conversationId());
            Instant now = now();
            if (!CaseVocabulary.RESOLUTION_UPHOLD.equals(message.resolution())) {
                reverse(transaction, facts, appellant, message, actor, now);
            }
            var appended = threads.append(transaction, facts.caseId(), appellant,
                    CaseVocabulary.KIND_MANAGER_REPLY, CaseVocabulary.ACTOR_MANAGER, actor, message.body());
            long actionId = store.addAction(new CaseRecords.Action(0, facts.caseId(),
                    CaseVocabulary.ACTION_MANAGER_REPLY, CaseVocabulary.ACTOR_MANAGER, actor, now,
                    appended.messageId(), appellant, null, appeal.actionId(), message.resolution(),
                    message.basisRef(), null));
            notifications.create(transaction, CaseVocabulary.EVENT_APPEAL_RESOLVED,
                    "case:" + facts.caseId() + ":appeal:" + appeal.actionId() + ":resolved",
                    new ResourceRef("case", facts.caseId()), Set.of(appellant),
                    Map.of("case_id", Long.toString(facts.caseId()), "resolution", message.resolution()), now);
            store.touch(facts.caseId(), now);
            audit(transaction, "case.appeal.resolve", facts.caseId(), actor);
            return messageResponse(facts, conversationId, appended, actionId, CaseVocabulary.KIND_MANAGER_REPLY);
        }

        /**
         * Reverses or adjusts the recorded enforcement that affected the appellant. The adapter
         * resolves the subject record from the case source, so no subject identifier is accepted
         * from the client and no state is changed when the capability is unavailable.
         */
        private void reverse(WriteTransaction transaction, CaseRecords.Facts facts, long appellant,
                             CaseCommands.Message message, long manager, Instant now) {
            if (enforcement == null) {
                throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "撤销或调整须由处置执行提供");
            }
            var recorded = store.enforcements(facts.caseId()).stream()
                    .filter(item -> item.affectedAccountIds().contains(appellant))
                    .reduce((first, second) -> second)
                    .orElseThrow(() -> new BusinessError("STATE_CONFLICT", 409, "没有可撤销的执行记录"));
            String basisRef = "case:" + facts.caseId();
            var outcomes = enforcement.reverse(transaction, transaction.context(), facts.caseId(), recorded,
                    message.resolution(), basisRef, message.basisRef(), now);
            for (var outcome : outcomes) {
                store.addEnforcement(new CaseRecords.Enforcement(outcome.enforcementId(), facts.caseId(),
                        outcome.action(), outcome.targetType(), outcome.targetId(), basisRef, manager, now,
                        outcome.resultType(), outcome.resultId(), outcome.resultStatus(), outcome.previousState(),
                        outcome.currentState(), outcome.affectedAccountIds(), null, null, now));
                if (!outcome.affectedAccountIds().isEmpty()) {
                    notifications.create(transaction, enforcementEvent(outcome.action()),
                            "case:" + facts.caseId() + ":" + outcome.enforcementId() + ":reversed",
                            new ResourceRef("case", facts.caseId()),
                            Set.copyOf(outcome.affectedAccountIds()),
                            Map.of("case_id", Long.toString(facts.caseId()),
                                    "reason", message.basisRef() == null ? "" : message.basisRef()), now);
                }
            }
            store.markEnforcementLifted(facts.caseId(), recorded.enforcementId(), manager,
                    message.basisRef() == null ? message.resolution() : message.basisRef(), now);
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
            var decision = request.decision();
            var instructions = instructions(decision);
            // Subject execution locks the trade before the case, so a decision with enforcements
            // writes the decision first and lets the execution adapter take the ordered locks.
            var facts = instructions.isEmpty()
                    ? store.lock(transaction, request.caseId())
                    : store.require(request.caseId());
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
            if (decision.decisionKind() == null || !CaseVocabulary.DECISION_KINDS.contains(decision.decisionKind())) {
                throw new BusinessError("INPUT_INVALID", 422, "decision_kind 取值无效");
            }
            String reason = requiredText(decision.reason(), settings.getMaxReasonLength(), "决定理由");
            if (decision.basisRefs().isEmpty()) {
                throw new BusinessError("BASIS_REQUIRED", 422, "决定须给出依据");
            }
            var evidenceIds = store.evidence(facts.caseId()).stream()
                    .map(CaseRecords.Evidence::evidenceId).collect(Collectors.toSet());
            for (String basis : decision.basisRefs()) {
                var matcher = EVIDENCE_REF.matcher(basis == null ? "" : basis.trim());
                if (matcher.matches() && !evidenceIds.contains(Long.parseLong(matcher.group(1)))) {
                    throw new BusinessError("BASIS_REQUIRED", 422, "依据不属于本事项");
                }
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
                persisted.affectedAccountIds().forEach(id -> scope.add("account:" + id));
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
                        outcome.currentState(), outcome.affectedAccountIds(), null, null, now));
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
            String event = enforcementEvent(outcome.action());
            notifications.create(transaction, event,
                    "case:" + facts.caseId() + ":" + outcome.enforcementId() + ":affected",
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
            for (long accountId : store.relatedAccountIds(facts.caseId())) {
                threads.findConversation(facts.caseId(), accountId)
                        .ifPresent(id -> resources.add(new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION,
                                List.of(id))));
            }
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
            for (long accountId : store.relatedAccountIds(facts.caseId())) {
                threads.archive(transaction, facts.caseId(), accountId);
            }
            facts = store.archive(facts.caseId(), now);
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_CLOSE,
                    CaseVocabulary.ACTOR_MANAGER, manager, now, null, null, null, null, null, null, null));
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

    // ------------------------------------------------------------------ helpers

    private JsonNode digest(long caseId, Object input) {
        var node = json.createObjectNode();
        node.put("case_id", caseId);
        node.set("input", json.valueToTree(input));
        return node;
    }

    private static String enforcementEvent(String action) {
        return switch (action) {
            case "freeze_trade" -> CaseVocabulary.EVENT_TRADE_FROZEN;
            case "lift_trade_freeze" -> CaseVocabulary.EVENT_TRADE_UNFROZEN;
            case "adjust_trade_status" -> CaseVocabulary.EVENT_TRADE_ADJUSTED;
            default -> CaseVocabulary.EVENT_DECIDED;
        };
    }

    private static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    private List<CaseRecords.EnforcementInstruction> instructions(CaseCommands.Decision decision) {
        var list = new ArrayList<CaseRecords.EnforcementInstruction>();
        for (var item : decision.enforcements()) {
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
            if ("adjust_trade_status".equals(item.action()) && (expected == null || expected.isBlank())) {
                throw new BusinessError("INPUT_INVALID", 422, "调整交易状态须给出目标状态");
            }
            list.add(new CaseRecords.EnforcementInstruction(UUID.randomUUID().toString(), item.action(),
                    item.targetType(), item.targetId(), expected));
        }
        return list;
    }

    private void attachEvidence(WriteTransaction transaction, long caseId, long reporter, List<Long> fileIds) {
        if (fileIds.isEmpty()) {
            return;
        }
        var ordered = fileIds.stream().distinct().sorted().toList();
        var references = files.attach(transaction, caseId, reporter, ordered);
        Instant now = now();
        for (int index = 0; index < ordered.size(); index++) {
            Long referenceId = index < references.size() ? references.get(index) : null;
            store.addEvidence(caseId, ordered.get(index), referenceId, reporter, now);
        }
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
