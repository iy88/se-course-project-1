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
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Publishes an archived report's result and notifies its reporter. */
final class PublishCaseResult
        implements WriteExecutor.UseCase<PublishCaseResult.Request, PublishCaseResult.Request> {
    private final CaseLifecycleStore store;
    private final CasePorts.Managers managers;
    private final CasePorts.Notifications notifications;
    private final CaseSettings settings;
    private final JsonMapper json;
    private final Clock clock;

    PublishCaseResult(CaseLifecycleStore store, CasePorts.Managers managers, CasePorts.Notifications notifications,
                      CaseSettings settings, JsonMapper json, Clock clock) {
        this.store = Objects.requireNonNull(store);
        this.managers = Objects.requireNonNull(managers);
        this.notifications = Objects.requireNonNull(notifications);
        this.settings = Objects.requireNonNull(settings);
        this.json = Objects.requireNonNull(json);
        this.clock = Objects.requireNonNull(clock);
    }

    record Request(long caseId, CaseCommands.Publish publish) {
    }

    @Override
    public JsonNode digestInput(Request request) {
        return CaseWriteSupport.digest(json, request.caseId(), request.publish());
    }

    @Override
    public LockPlan prepare(ExecutionContext context, Request request) {
        return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())));
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
        if (!facts.archived()) {
            throw new BusinessError("STATE_CONFLICT", 409, "事项尚未结案");
        }
        if (facts.publicResultAt() != null) {
            throw new BusinessError("STATE_CONFLICT", 409, "结果已公开");
        }
        if (!CaseVocabulary.REPORT.equals(facts.caseType())) {
            throw new BusinessError("STATE_CONFLICT", 409, "仅举报事项可公开结果");
        }
        String summary = CaseWriteSupport.requiredText(request.publish().summary(),
                settings.getMaxReasonLength(), "公开结论");
        String reason = CaseWriteSupport.requiredText(request.publish().reason(),
                settings.getMaxNoteLength(), "公开原因");
        Instant now = CaseWriteSupport.now(clock);
        facts = store.publish(facts.caseId(), summary, reason, manager, now);
        store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_PUBLISH_RESULT,
                CaseVocabulary.ACTOR_MANAGER, manager, now, null, null, null, null, null, null, null));
        if (facts.reporterAccountId() != null) {
            notifications.create(transaction, CaseVocabulary.EVENT_RESULT_PUBLISHED,
                    "case:" + facts.caseId() + ":result_published",
                    new ResourceRef("case", facts.caseId()), Set.of(facts.reporterAccountId()),
                    Map.of("case_id", Long.toString(facts.caseId())), now);
        }
        CaseWriteSupport.audit(json, transaction, "case.publish_result", facts.caseId(), manager);
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(facts.caseId()));
        body.put("public_result_at", facts.publicResultAt().toString());
        return new WriteResult.Response<>(200, body, new ResourceRef("case", facts.caseId()));
    }
}
