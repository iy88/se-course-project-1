package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.Locale;
import java.util.Objects;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Minimum orchestration for product-review claim and decision: the product review capability
 * keeps the audit authority and the case port keeps fixed claim ownership. The application only
 * orders the two subject calls and the shared transaction/lock/audit boundary.
 */
public final class ReviewApplication implements WriteExecutor.UseCase<ReviewCommand, Boolean> {
    public static final String CLAIM_OPERATION = "case.review.claim";
    public static final String DECISION_OPERATION = "case.review.decide";

    private final WriteExecutor writes;
    private final ProductReviewPort products;
    private final CaseReviewPort cases;
    private final JsonMapper json;

    public ReviewApplication(WriteExecutor writes, ProductReviewPort products, CaseReviewPort cases,
                             JsonMapper json) {
        this.writes = Objects.requireNonNull(writes);
        this.products = Objects.requireNonNull(products);
        this.cases = Objects.requireNonNull(cases);
        this.json = Objects.requireNonNull(json);
    }

    public WriteResult<JsonNode> execute(ExecutionContext context, String idempotencyKey, ReviewCommand command) {
        String operation = command.action() == ReviewAction.CLAIM ? CLAIM_OPERATION : DECISION_OPERATION;
        return writes.run(context, operation, idempotencyKey, command, this);
    }

    @Override
    public JsonNode digestInput(ReviewCommand request) {
        var root = json.createObjectNode();
        root.put("case_id", request.caseId());
        root.put("audit_id", request.auditId());
        root.put("action", request.action().name());
        if (request.reason() != null) {
            root.put("reason", request.reason());
        }
        if (request.categoryDecision() != null) {
            root.put("category_application_decision", request.categoryDecision().name());
            root.put("category_application_reason", request.categoryReason());
        }
        var basis = root.putArray("basis_refs");
        request.basisRefs().forEach(basis::add);
        return root;
    }

    @Override
    public LockPlan prepare(ExecutionContext context, ReviewCommand request) {
        return plan(request).lockPlan();
    }

    @Override
    public Boolean qualify(ExecutionContext context, ReviewCommand request, LockPlan plan) {
        cases.requireManager(context, request);
        return Boolean.TRUE;
    }

    @Override
    public void requireReplayAccess(ExecutionContext context, Boolean qualifications, ResourceRef resource) {
        if (!"case".equals(resource.type())) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
        }
        cases.requireReplayAccess(context, resource.id());
    }

    @Override
    public WriteResult.Response<?> write(WriteTransaction transaction, ReviewCommand command,
                                         Boolean qualifications, LockPlan prepared) {
        var plan = plan(command);
        var missing = plan.missingFrom(prepared);
        if (!missing.accounts().isEmpty() || !missing.resources().isEmpty()) {
            throw new LockPlan.Changed(missing);
        }
        plan.acquire(transaction);
        cases.requireManager(transaction.context(), command);

        var subject = command.action() == ReviewAction.CLAIM
                ? products.claim(transaction, command)
                : products.decide(transaction, command);
        if (command.action() == ReviewAction.CLAIM) {
            cases.claim(transaction, command);
        } else {
            cases.recordDecision(transaction, command, subject);
        }
        if (!subject.alreadyEffective()) {
            var facts = json.createObjectNode();
            facts.put("case_id", command.caseId());
            facts.put("audit_id", command.auditId());
            facts.put("action", command.action().name());
            facts.put("previous_state", subject.previousState());
            facts.put("current_state", subject.currentState());
            var basis = facts.putArray("basis_refs");
            command.basisRefs().forEach(basis::add);
            transaction.audit("case.review." + command.action().name().toLowerCase(Locale.ROOT),
                    new ResourceRef("product_audit", command.auditId()), new ResourceRef("case", command.caseId()),
                    facts);
        }

        var outcome = new ReviewOutcome(command.caseId(), command.auditId(), command.action(), subject.auditRef(),
                subject.previousState(), subject.currentState(), subject.alreadyEffective());
        return new WriteResult.Response<>(200, outcome, new ResourceRef("case", command.caseId()));
    }

    private SubjectPlan plan(ReviewCommand command) {
        return products.prepare(command).merge(cases.prepare(command));
    }
}
