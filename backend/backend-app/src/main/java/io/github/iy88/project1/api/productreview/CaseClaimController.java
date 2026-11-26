package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.core.WriteResult;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/admin/cases")
class CaseClaimController {
    private final ReviewHttpSupport support;

    CaseClaimController(ReviewHttpSupport support) {
        this.support = support;
    }

    @PostMapping("/{case_id}/claim")
    ResponseEntity<JsonNode> claim(@PathVariable("case_id") String caseId,
                                   @RequestHeader("Idempotency-Key") String idempotencyKey,
                                   HttpServletRequest request) {
        var context = support.context(request);
        long id = EntityIds.requirePositive(caseId, "case_id");
        WriteResult<JsonNode> result = support.reviews().claim(context, idempotencyKey, id);
        return ResponseEntity.status(result.status()).body(result.data());
    }
}
