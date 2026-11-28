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

/** References the exact reported message as a manager-owned platform record. */
final class ReferenceCaseEvidence
        implements WriteExecutor.UseCase<ReferenceCaseEvidence.Request, ReferenceCaseEvidence.Request> {
    private final CaseLifecycleStore store;
    private final CasePorts.Targets targets;
    private final CasePorts.Managers managers;
    private final JsonMapper json;
    private final Clock clock;

    ReferenceCaseEvidence(CaseLifecycleStore store, CasePorts.Targets targets, CasePorts.Managers managers,
                          JsonMapper json, Clock clock) {
        this.store = Objects.requireNonNull(store);
        this.targets = Objects.requireNonNull(targets);
        this.managers = Objects.requireNonNull(managers);
        this.json = Objects.requireNonNull(json);
        this.clock = Objects.requireNonNull(clock);
    }

    record Request(long caseId, CaseCommands.EvidenceReference reference) {
    }

    @Override
    public JsonNode digestInput(Request request) {
        return CaseWriteSupport.digest(json, request.caseId(), request.reference());
    }

    @Override
    public LockPlan prepare(ExecutionContext context, Request request) {
        return new LockPlan(Map.of(), Set.of(CaseLifecycleStore.lockKey(request.caseId())));
    }

    @Override
    public Request qualify(ExecutionContext context, Request request, LockPlan plan) {
        requireEvidenceManager(context);
        return request;
    }

    @Override
    public void requireReplayAccess(ExecutionContext context, Request qualification, ResourceRef resource) {
        if (!CaseVocabulary.SOURCE_CASE.equals(resource.type())) {
            throw CaseWriteSupport.notVisible();
        }
        var facts = store.find(resource.id()).orElseThrow(CaseWriteSupport::notVisible);
        if (!facts.claimedBy(CaseWriteSupport.actor(context))) {
            throw CaseWriteSupport.notVisible();
        }
    }

    @Override
    public WriteResult.Response<?> write(WriteTransaction transaction, Request request, Request qualification,
                                         LockPlan plan) {
        long manager = CaseWriteSupport.actor(transaction.context());
        var facts = store.lock(transaction, request.caseId());
        CaseWriteSupport.requireLifecycle(facts);
        if (!facts.claimedBy(manager)) {
            throw CaseWriteSupport.notVisible();
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
                reference.messageId(), scope, manager, CaseWriteSupport.now(clock));
        CaseWriteSupport.audit(json, transaction, "case.evidence.reference", facts.caseId(), manager);
        return new WriteResult.Response<>(201, evidenceReference(facts.caseId(), evidenceId,
                reference.messageId(), false), new ResourceRef("case", facts.caseId()));
    }

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
        CaseWriteSupport.actor(context);
        try {
            managers.requireManagerForWrite(context);
        } catch (BusinessError denied) {
            throw CaseWriteSupport.notVisible();
        }
    }
}
