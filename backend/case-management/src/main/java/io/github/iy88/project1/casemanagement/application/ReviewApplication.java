package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.temporal.ChronoUnit;
import java.util.Locale;
import java.util.Objects;
import java.util.Optional;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Coordinates product-review claim and decision. The product adapter keeps review authority,
 * content snapshots and category rules; the case store keeps fixed claim ownership. The shared
 * {@link WriteExecutor} owns the transaction, idempotency, account qualification locks and the
 * ordered resource lock plan.
 */
public class ReviewApplication {
    public static final String CLAIM_OPERATION = "case.review.claim";
    public static final String DECISION_OPERATION = "case.review.decide";

    private final WriteExecutor writes;
    private final ReviewCaseStore cases;
    private final JsonMapper json;
    private final Optional<ProductReviewPort> products;
    private final Optional<ReviewManagerAccess> managers;
    private final Optional<ReviewNotifications> notifications;
    private final Clock clock;

    /**
     * Dependencies that are not assembled in this stage are passed as {@code null}; calling the
     * affected operation then returns {@code DEPENDENCY_UNAVAILABLE} without writing.
     */
    public ReviewApplication(WriteExecutor writes, ReviewCaseStore cases, JsonMapper json,
                             ProductReviewPort products, ReviewManagerAccess managers,
                             ReviewNotifications notifications) {
        this(writes, cases, json, products, managers, notifications, Clock.systemUTC());
    }

    public ReviewApplication(WriteExecutor writes, ReviewCaseStore cases, JsonMapper json,
                             ProductReviewPort products, ReviewManagerAccess managers,
                             ReviewNotifications notifications, Clock clock) {
        this.writes = Objects.requireNonNull(writes);
        this.cases = Objects.requireNonNull(cases);
        this.json = Objects.requireNonNull(json);
        this.products = Optional.ofNullable(products);
        this.managers = Optional.ofNullable(managers);
        this.notifications = Optional.ofNullable(notifications);
        this.clock = Objects.requireNonNull(clock);
    }

    public WriteResult<JsonNode> claim(ExecutionContext context, String idempotencyKey, long caseId) {
        var product = product();
        manager().requireManager(context, "ACTION_NOT_ALLOWED", 403);
        var claim = new ReviewClaim(caseId, clock.instant().truncatedTo(ChronoUnit.MICROS));
        return writes.run(context, CLAIM_OPERATION, idempotencyKey, claim, new ClaimUseCase(product));
    }

    public WriteResult<JsonNode> decide(ExecutionContext context, String idempotencyKey,
                                        ReviewDecisionInput input) {
        var product = product();
        manager().requireManager(context, "RESOURCE_NOT_VISIBLE", 404);
        var notify = notification();
        var decision = new ReviewDecision(input, clock.instant().truncatedTo(ChronoUnit.MICROS));
        return writes.run(context, DECISION_OPERATION, idempotencyKey, decision,
                new DecisionUseCase(product, notify));
    }

    public JsonNode detail(ExecutionContext context, long auditId) {
        var product = product();
        manager().requireManager(context, "RESOURCE_NOT_VISIBLE", 404);
        var claim = cases.read(product.caseIdForAudit(auditId));
        if (!claim.claimedBy(actor(context))) {
            throw notVisible();
        }
        return ReviewWire.detail(json, product.detail(context, auditId), claim);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode todos(ExecutionContext context, String ownershipValue, String kindValue,
                          int page, int pageSize) {
        var product = product();
        manager().requireManager(context, "MANAGEMENT_NOT_ALLOWED", 403);
        var ownership = TodoOwnership.parse(ownershipValue);
        String kind = kindValue == null ? TodoKinds.PRODUCT_REVIEW : kindValue;
        if (!TodoKinds.legal(kind)) {
            throw new BusinessError("INPUT_INVALID", 422, "待办类型无效");
        }
        if (page <= 0 || pageSize <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        var result = product.todos(new TodoQuery(actor(context), ownership, kind, page, pageSize));
        return ReviewWire.todos(json, result.items(), page, pageSize, result.total(), result.countsByKind(),
                result.asOf());
    }

    private ProductReviewPort product() {
        return products.orElseThrow(ReviewApplication::dependencyUnavailable);
    }

    private ReviewManagerAccess manager() {
        return managers.orElseThrow(ReviewApplication::dependencyUnavailable);
    }

    private ReviewNotifications notification() {
        return notifications.orElseThrow(ReviewApplication::dependencyUnavailable);
    }

    private static BusinessError dependencyUnavailable() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "审核依赖暂不可用");
    }

    private static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "审核不可见");
    }

    private static long actor(ExecutionContext context) {
        return Long.parseLong(context.actorId());
    }

    private static void requirePrepared(SubjectPlan subjectPlan, LockPlan prepared) {
        var missing = subjectPlan.missingFrom(prepared);
        if (!missing.accounts().isEmpty() || !missing.resources().isEmpty()) {
            throw new LockPlan.Changed(missing);
        }
    }

    private final class ClaimUseCase implements WriteExecutor.UseCase<ReviewClaim, Boolean> {
        private final ProductReviewPort product;

        private ClaimUseCase(ProductReviewPort product) {
            this.product = product;
        }

        @Override
        public JsonNode digestInput(ReviewClaim request) {
            return json.createObjectNode().put("case_id", request.caseId());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, ReviewClaim request) {
            return product.prepareClaim(request.caseId()).merge(cases.plan(request.caseId())).lockPlan();
        }

        @Override
        public Boolean qualify(ExecutionContext context, ReviewClaim request, LockPlan plan) {
            manager().requireManagerForWrite(context, "ACTION_NOT_ALLOWED", 403);
            return Boolean.TRUE;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, Boolean qualifications, ResourceRef resource) {
            if (!"case".equals(resource.type())) {
                throw notVisible();
            }
            cases.requireClaimedBy(context, resource.id());
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, ReviewClaim request,
                                             Boolean qualifications, LockPlan prepared) {
            var subjectPlan = product.prepareClaim(request.caseId()).merge(cases.plan(request.caseId()));
            requirePrepared(subjectPlan, prepared);
            subjectPlan.acquire(transaction);

            long auditId = product.requirePendingForClaim(request.caseId());
            var current = cases.read(request.caseId());
            long actor = actor(transaction.context());

            if (current.claimed()) {
                if (!current.claimedBy(actor)) {
                    throw new BusinessError("CASE_ALREADY_CLAIMED", 409, "事项已被其他管理员认领");
                }
                return new WriteResult.Response<>(200,
                        ReviewWire.claim(json, current, actor, current.claimedAt(), true),
                        new ResourceRef("case", current.caseId()));
            }

            cases.claim(request.caseId(), actor, request.occurredAt());
            auditClaim(transaction, request, auditId);
            return new WriteResult.Response<>(200,
                    ReviewWire.claim(json, current, actor, request.occurredAt(), false),
                    new ResourceRef("case", current.caseId()));
        }

        private void auditClaim(WriteTransaction transaction, ReviewClaim request, long auditId) {
            var facts = json.createObjectNode();
            facts.put("case_id", request.caseId());
            facts.put("audit_id", auditId);
            facts.put("action", "claim");
            facts.put("previous_state", "pending");
            facts.put("current_state", "claimed");
            transaction.audit("case.review.claim", new ResourceRef("product_audit", auditId),
                    new ResourceRef("case", request.caseId()), facts);
        }
    }

    private final class DecisionUseCase implements WriteExecutor.UseCase<ReviewDecision, Boolean> {
        private final ProductReviewPort product;
        private final ReviewNotifications notify;

        private DecisionUseCase(ProductReviewPort product, ReviewNotifications notify) {
            this.product = product;
            this.notify = notify;
        }

        @Override
        public JsonNode digestInput(ReviewDecision request) {
            var input = request.input();
            var root = json.createObjectNode();
            root.put("audit_id", input.auditId());
            root.put("decision", input.action().name());
            if (input.reason() != null) {
                root.put("reason", input.reason());
            }
            var banned = root.putArray("banned_item_ids");
            input.bannedItemIds().forEach(banned::add);
            if (input.categoryAction() != null) {
                root.put("category_application_decision", input.categoryAction().name());
                root.put("category_application_reason", input.categoryReason());
            }
            return root;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, ReviewDecision request) {
            var productPlan = product.prepareDecision(request.input().auditId());
            return productPlan.locks().merge(cases.plan(productPlan.caseId())).lockPlan();
        }

        @Override
        public Boolean qualify(ExecutionContext context, ReviewDecision request, LockPlan plan) {
            manager().requireManagerForWrite(context, "RESOURCE_NOT_VISIBLE", 404);
            return Boolean.TRUE;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, Boolean qualifications, ResourceRef resource) {
            if (!"case".equals(resource.type())) {
                throw notVisible();
            }
            cases.requireClaimedBy(context, resource.id());
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, ReviewDecision request,
                                             Boolean qualifications, LockPlan prepared) {
            var input = request.input();
            var productPlan = product.prepareDecision(input.auditId());
            var subjectPlan = productPlan.locks().merge(cases.plan(productPlan.caseId()));
            requirePrepared(subjectPlan, prepared);
            subjectPlan.acquire(transaction);

            // Category references can change between reading the plan and locking the product.
            var lockedPlan = product.prepareDecision(input.auditId());
            requirePrepared(lockedPlan.locks().merge(cases.plan(lockedPlan.caseId())), subjectPlan.lockPlan());
            var current = cases.read(lockedPlan.caseId());
            long actor = actor(transaction.context());
            if (!current.claimedBy(actor)) {
                throw notVisible();
            }

            var result = product.decide(transaction, request);
            cases.recordDecision(current.caseId(), actor, request.occurredAt());
            auditDecision(transaction, request, result);
            notify.reviewDecided(transaction, result.sellerAccountId(), result.auditId(), result.productId(),
                    result.status(), result.rejectionReason(), request.occurredAt());
            return new WriteResult.Response<>(200, ReviewWire.decision(json, result),
                    new ResourceRef("case", result.caseId()));
        }

        private void auditDecision(WriteTransaction transaction, ReviewDecision request, DecisionResult result) {
            var input = request.input();
            var facts = json.createObjectNode();
            facts.put("case_id", result.caseId());
            facts.put("audit_id", result.auditId());
            facts.put("product_id", result.productId());
            facts.put("action", input.action().name().toLowerCase(Locale.ROOT));
            facts.put("previous_state", "pending");
            facts.put("current_state", result.status());
            var basis = facts.putArray("banned_item_ids");
            input.bannedItemIds().forEach(basis::add);
            transaction.audit("case.review." + input.action().name().toLowerCase(Locale.ROOT),
                    new ResourceRef("product_audit", result.auditId()),
                    new ResourceRef("case", result.caseId()), facts);
        }
    }
}
