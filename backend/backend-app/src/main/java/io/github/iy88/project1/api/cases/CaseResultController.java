package io.github.iy88.project1.api.cases;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/** Anonymous public case results (API-CASE-009). */
@RestController
@RequestMapping("/api/v1/case-results")
@Profile("!dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class CaseResultController {
    private final CaseHttpSupport support;

    CaseResultController(CaseHttpSupport support) {
        this.support = support;
    }

    @GetMapping
    ResponseEntity<JsonNode> results(HttpServletRequest request,
                                     @RequestParam(name = "target_type", required = false) String targetType,
                                     @RequestParam(name = "target_id", required = false) String targetId,
                                     @RequestParam(name = "conversation_kind", required = false) String conversationKind,
                                     @RequestParam(name = "conversation_id", required = false) String conversationId,
                                     @RequestParam(required = false) Integer page,
                                     @RequestParam(name = "page_size", required = false) Integer pageSize) {
        var context = support.context(request);
        Long id = targetId == null ? null : CaseIds.body(targetId, "target_id");
        Long conversation = conversationId == null ? null : CaseIds.body(conversationId, "conversation_id");
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(support.queries().results(context, targetType, id, conversationKind, conversation,
                        page == null ? 1 : page, pageSize == null ? 20 : pageSize));
    }
}
