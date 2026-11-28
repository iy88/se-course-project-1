package io.github.iy88.project1.casemanagement.application;

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
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Claims one report for the acting manager. */
final class ClaimCase implements WriteExecutor.UseCase<ClaimCase.Request, Boolean> {
    private final CaseLifecycleStore store;
    private final CasePorts.Managers managers;
    private final JsonMapper json;
    private final Clock clock;

    ClaimCase(CaseLifecycleStore store, CasePorts.Managers managers, JsonMapper json, Clock clock) {
        this.store = Objects.requireNonNull(store);
        this.managers = Objects.requireNonNull(managers);
        this.json = Objects.requireNonNull(json);
        this.clock = Objects.requireNonNull(clock);
    }

    record Request(long caseId) {
    }

    @Override
    public JsonNode digestInput(Request request) {
        return json.createObjectNode().put("case_id", request.caseId());
    }

    @Override
    public LockPlan prepare(ExecutionContext context, Request request) {
        return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())));
    }

    @Override
    public Boolean qualify(ExecutionContext context, Request request, LockPlan plan) {
        managers.requireManagerForWrite(context);
        return Boolean.TRUE;
    }

    @Override
    public void requireReplayAccess(ExecutionContext context, Boolean qualification, ResourceRef resource) {
        if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
            throw CaseWriteSupport.notVisible();
        }
        var facts = store.find(resource.id()).orElseThrow(CaseWriteSupport::notVisible);
        if (!facts.claimedBy(CaseWriteSupport.actor(context))) {
            throw CaseWriteSupport.notVisible();
        }
    }

    @Override
    public WriteResult.Response<?> write(WriteTransaction transaction, Request request, Boolean qualification,
                                         LockPlan plan) {
        long manager = CaseWriteSupport.actor(transaction.context());
        var facts = store.lock(transaction, request.caseId());
        CaseWriteSupport.requireLifecycle(facts);
        if (facts.archived()) {
            throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
        }
        boolean alreadyClaimed = facts.claimedBy(manager);
        if (!alreadyClaimed) {
            if (facts.claimedManagerId() != null) {
                throw new BusinessError("CASE_ALREADY_CLAIMED", 409, "事项已被其他管理员认领");
            }
            facts = store.claim(facts.caseId(), manager, CaseWriteSupport.now(clock));
            store.addAction(new CaseRecords.Action(0, facts.caseId(), CaseVocabulary.ACTION_CLAIM,
                    CaseVocabulary.ACTOR_MANAGER, manager, CaseWriteSupport.now(clock),
                    null, null, null, null, null, null, null));
        }
        CaseWriteSupport.audit(json, transaction, "case.claim", facts.caseId(), manager);
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(facts.caseId()));
        body.put("case_status", facts.caseStatus());
        body.put("claimed_manager_id", Long.toString(facts.claimedManagerId()));
        body.put("claimed_at", facts.claimedAt().toString());
        body.put("already_claimed", alreadyClaimed);
        return new WriteResult.Response<>(200, body, new ResourceRef("case", facts.caseId()));
    }
}
