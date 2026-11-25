package io.github.iy88.project1.api.productreview;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.github.iy88.project1.casemanagement.application.ReviewAction;
import io.github.iy88.project1.casemanagement.application.ReviewDecisionInput;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.WriteResult;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/admin/product-reviews")
class ProductReviewController {
    private final ReviewHttpSupport support;

    ProductReviewController(ReviewHttpSupport support) {
        this.support = support;
    }

    @GetMapping("/{audit_id}")
    ResponseEntity<JsonNode> detail(@PathVariable("audit_id") String auditId, HttpServletRequest request) {
        var context = support.context(request);
        long id = EntityIds.requirePositive(auditId, "audit_id");
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(support.reviews().detail(context, id));
    }

    @PostMapping("/{audit_id}/decision")
    ResponseEntity<JsonNode> decide(@PathVariable("audit_id") String auditId,
                                    @RequestHeader("Idempotency-Key") String idempotencyKey,
                                    @RequestBody DecisionRequest body, HttpServletRequest request) {
        var context = support.context(request);
        long id = EntityIds.requirePositive(auditId, "audit_id");
        var input = new ReviewDecisionInput(id, action(body.decision), body.reason,
                EntityIds.requirePositive(body.bannedItemIds, "banned_item_ids"),
                categoryAction(body.categoryApplicationDecision), body.categoryApplicationReason);
        WriteResult<JsonNode> result = support.reviews().decide(context, idempotencyKey, input);
        return ResponseEntity.status(result.status()).body(result.data());
    }

    private static ReviewAction action(String value) {
        return switch (value == null ? "" : value) {
            case "approved" -> ReviewAction.APPROVE;
            case "rejected" -> ReviewAction.REJECT;
            default -> throw new BusinessError("INPUT_INVALID", 422, "审核结论无效");
        };
    }

    private static ReviewAction categoryAction(String value) {
        if (value == null) {
            return null;
        }
        return switch (value) {
            case "approved" -> ReviewAction.APPROVE;
            case "rejected" -> ReviewAction.REJECT;
            default -> throw new BusinessError("INPUT_INVALID", 422, "分类申请结论无效");
        };
    }

    record DecisionRequest(String decision, String reason,
                           @JsonProperty("category_application_decision") String categoryApplicationDecision,
                           @JsonProperty("category_application_reason") String categoryApplicationReason,
                           @JsonProperty("banned_item_ids") List<String> bannedItemIds) {
    }
}
