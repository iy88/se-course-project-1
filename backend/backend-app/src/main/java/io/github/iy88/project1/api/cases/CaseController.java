package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.WriteResult;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/** User-facing case endpoints API-CASE-001, 002, 003, 006 and 010. */
@RestController
@RequestMapping("/api/v1/cases")
@Profile("!dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class CaseController {
    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";

    private final CaseHttpSupport support;

    CaseController(CaseHttpSupport support) {
        this.support = support;
    }

    @PostMapping
    ResponseEntity<JsonNode> submit(HttpServletRequest request,
                                    @RequestBody(required = false) CaseRequests.Report body,
                                    @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        var command = CaseIds.report(body);
        return write(support.application().submit(context, idempotency(key), command));
    }

    @GetMapping
    ResponseEntity<JsonNode> list(HttpServletRequest request,
                                  @RequestParam(required = false) String scope,
                                  @RequestParam(required = false) String status,
                                  @RequestParam(required = false) Boolean archived,
                                  @RequestParam(required = false) Integer page,
                                  @RequestParam(name = "page_size", required = false) Integer pageSize) {
        var context = support.context(request);
        int resolvedPage = page == null ? 1 : page;
        int resolvedSize = pageSize == null ? 20 : pageSize;
        return ok(support.queries().page(context, scope, status, archived, resolvedPage, resolvedSize));
    }

    @GetMapping("/{case_id}")
    ResponseEntity<JsonNode> detail(HttpServletRequest request,
                                    @PathVariable("case_id") String caseId) {
        var context = support.context(request);
        return ok(support.queries().detail(context, CaseIds.path(caseId)));
    }

    @PostMapping("/{case_id}/supplements")
    ResponseEntity<JsonNode> supplement(HttpServletRequest request,
                                        @PathVariable("case_id") String caseId,
                                        @RequestBody(required = false) CaseRequests.Supplement body,
                                        @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().supplement(context, idempotency(key), CaseIds.path(caseId),
                CaseIds.supplement(body)));
    }

    @PostMapping("/{case_id}/messages")
    ResponseEntity<JsonNode> message(HttpServletRequest request,
                                     @PathVariable("case_id") String caseId,
                                     @RequestBody(required = false) CaseRequests.Message body,
                                     @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().postMessage(context, idempotency(key), CaseIds.path(caseId),
                CaseIds.message(body)));
    }

    private static ResponseEntity<JsonNode> write(WriteResult<?> result) {
        return ResponseEntity.status(result.status()).cacheControl(CacheControl.noStore())
                .body((JsonNode) result.data());
    }

    private static ResponseEntity<JsonNode> ok(JsonNode body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }

    private static String idempotency(String value) {
        if (value == null || value.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "缺少 Idempotency-Key");
        }
        return value;
    }
}
