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
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Sends one manager inquiry to a related account of the claimed case. */
final class InquireCase implements WriteExecutor.UseCase<InquireCase.Request, InquireCase.Request> {
    private final CaseLifecycleStore store;
    private final CasePorts.Targets targets;
    private final CasePorts.Managers managers;
    private final CasePorts.Notifications notifications;
    private final CasePorts.Threads threads;
    private final CaseSettings settings;
    private final JsonMapper json;
    private final Clock clock;

    InquireCase(CaseLifecycleStore store, CasePorts.Targets targets, CasePorts.Managers managers,
                CasePorts.Notifications notifications, CasePorts.Threads threads, CaseSettings settings,
                JsonMapper json, Clock clock) {
        this.store = Objects.requireNonNull(store);
        this.targets = Objects.requireNonNull(targets);
        this.managers = Objects.requireNonNull(managers);
        this.notifications = Objects.requireNonNull(notifications);
        this.threads = Objects.requireNonNull(threads);
        this.settings = Objects.requireNonNull(settings);
        this.json = Objects.requireNonNull(json);
        this.clock = Objects.requireNonNull(clock);
    }

    record Request(long caseId, CaseCommands.Inquiry inquiry) {
    }

    @Override
    public JsonNode digestInput(Request request) {
        return CaseWriteSupport.digest(json, request.caseId(), request.inquiry());
    }

    @Override
    public LockPlan prepare(ExecutionContext context, Request request) {
        var facts = store.find(request.caseId()).orElseThrow(CaseWriteSupport::notVisible);
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
    public Request qualify(ExecutionContext context, Request request, LockPlan plan) {
        managers.requireManagerForWrite(context);
        return request;
    }

    @Override
    public void requireReplayAccess(ExecutionContext context, Request qualification, ResourceRef resource) {
        if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
            throw CaseWriteSupport.notVisible();
        }
        var facts = store.find(resource.id()).orElseThrow(CaseWriteSupport::notVisible);
        if (!facts.claimedBy(CaseWriteSupport.actor(context))) {
            throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
        }
    }

    @Override
    public WriteResult.Response<?> write(WriteTransaction transaction, Request request, Request qualification,
                                         LockPlan plan) {
        long manager = CaseWriteSupport.actor(transaction.context());
        var facts = store.lock(transaction, request.caseId());
        CaseWriteSupport.requireLifecycle(facts);
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
        String scope = CaseWriteSupport.requiredText(request.inquiry().scopeText(),
                settings.getMaxNoteLength(), "问询范围");
        Instant now = CaseWriteSupport.now(clock);
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
        CaseWriteSupport.audit(json, transaction, "case.inquire", facts.caseId(), manager);
        var body = json.createObjectNode();
        body.put("inquiry_action_id", Long.toString(actionId));
        body.put("case_message_id", Long.toString(message.messageId()));
        body.set("thread", CaseWriteSupport.thread(json, conversationId));
        body.put("case_status", facts.caseStatus());
        body.put("notified_at", now.toString());
        return new WriteResult.Response<>(201, body, new ResourceRef("case", facts.caseId()));
    }
}
