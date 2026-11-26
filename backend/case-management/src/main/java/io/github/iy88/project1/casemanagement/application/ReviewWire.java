package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;
import java.util.List;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Builds the canonical HTTP response bodies that are also stored for idempotent replay. */
final class ReviewWire {
    private ReviewWire() {
    }

    static ObjectNode claim(JsonMapper json, CaseClaim current, long managerId, Instant claimedAt,
                            boolean alreadyClaimed) {
        var body = json.createObjectNode();
        body.put("case_id", Long.toString(current.caseId()));
        body.put("case_status", "claimed");
        body.put("claimed_manager_id", Long.toString(managerId));
        body.put("claimed_at", claimedAt.toString());
        body.put("already_claimed", alreadyClaimed);
        return body;
    }

    static ObjectNode decision(JsonMapper json, DecisionResult result) {
        var body = json.createObjectNode();
        body.put("audit_id", Long.toString(result.auditId()));
        body.put("status", result.status());
        body.put("case_id", Long.toString(result.caseId()));
        body.put("case_status", "decided");
        var product = body.putObject("product");
        product.put("id", Long.toString(result.productId()));
        product.put("lifecycle_state", result.lifecycleState());
        product.put("content_version", result.contentVersion());
        putCategoryApplication(body, result.categoryApplication());
        body.put("reviewed_content_version", result.reviewedContentVersion());
        body.put("decided_at", result.decidedAt().toString());
        return body;
    }

    static ObjectNode detail(JsonMapper json, ProductReviewDetail detail, CaseClaim claim) {
        var body = json.createObjectNode();
        body.put("audit_id", Long.toString(detail.auditId()));
        body.put("product_id", Long.toString(detail.productId()));
        body.put("case_id", Long.toString(detail.caseId()));
        body.put("status", detail.status());
        body.put("submitted_at", detail.submittedAt().toString());

        var seller = body.putObject("seller");
        seller.put("id", Long.toString(detail.seller().id()));
        seller.put("display_name", detail.seller().displayName());

        var claimNode = body.putObject("claim");
        claimNode.put("manager_id", Long.toString(claim.claimedManagerId()));
        claimNode.put("claimed_at", claim.claimedAt().toString());

        var content = body.putObject("current_content");
        content.put("title", detail.currentContent().title());
        content.put("description", detail.currentContent().description());
        var images = content.putArray("images");
        detail.currentContent().images().forEach(image -> {
            var item = images.addObject();
            item.put("file_id", Long.toString(image.fileId()));
            item.put("url", image.url().toString());
            item.put("expires_at", image.expiresAt().toString());
        });
        content.put("price_cents", detail.currentContent().priceCents());
        var categories = content.putArray("categories");
        detail.currentContent().categories().forEach(category -> {
            var item = categories.addObject();
            item.put("id", Long.toString(category.id()));
            item.put("name", category.name());
        });
        content.put("content_version", detail.currentContent().contentVersion());

        putCategoryApplication(body, detail.categoryApplication());

        var banned = body.putArray("banned_scope");
        detail.bannedScope().forEach(item -> {
            var node = banned.addObject();
            node.put("id", Long.toString(item.id()));
            node.put("group", item.group());
            node.put("content", item.content());
        });

        if (detail.reviewResult() == null) {
            body.putNull("review_result");
        } else {
            var result = detail.reviewResult();
            var node = body.putObject("review_result");
            node.put("decision", result.decision());
            node.put("reason", result.reason());
            node.put("reviewed_content_version", result.reviewedContentVersion());
            node.put("decided_at", result.decidedAt().toString());
            node.put("decided_by", Long.toString(result.decidedBy()));
        }
        return body;
    }

    static ObjectNode todos(JsonMapper json, List<TodoItem> items, int page, int pageSize, long total,
                            java.util.Map<String, Long> countsByKind, Instant asOf) {
        var body = json.createObjectNode();
        var rows = body.putArray("items");
        items.forEach(item -> {
            var row = rows.addObject();
            row.put("case_id", Long.toString(item.caseId()));
            row.put("kind", item.kind());
            row.put("case_type", item.kind());
            row.put("decision_kind", item.decisionKind());
            row.put("manager_id", item.managerId() == null ? null : item.managerId().toString());
            row.put("completed_at", item.completedAt() == null ? null : item.completedAt().toString());
            row.put("created_at", item.createdAt().toString());
            row.put("updated_at", item.updatedAt().toString());
            var summary = row.putObject("summary");
            summary.put("title", item.title());
            if (item.auditId() != null) {
                summary.put("audit_id", item.auditId().toString());
                summary.put("product_id", item.productId().toString());
            }
        });
        body.put("page", page);
        body.put("page_size", pageSize);
        body.put("total", total);
        var counts = body.putObject("counts_by_kind");
        TodoKinds.ALL.forEach(kind -> counts.put(kind, countsByKind.getOrDefault(kind, 0L)));
        body.put("as_of", asOf.toString());
        return body;
    }

    private static void putCategoryApplication(ObjectNode body, CategoryApplicationView application) {
        if (application == null) {
            body.putNull("category_application");
            return;
        }
        var node = body.putObject("category_application");
        node.put("application_id", Long.toString(application.applicationId()));
        node.put("proposed_name", application.proposedName());
        node.put("status", application.status());
    }
}
