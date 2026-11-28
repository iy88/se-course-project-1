package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.api.productreview.ReviewHttpSupport;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.ReviewApplication;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.trade.application.TradeApplication;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.ObjectProvider;
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
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/**
 * Management case endpoints. The claim route is shared with product review (S2-01): review cases
 * keep their own claim authority, lifecycle cases use the report/dispute claim.
 */
@RestController
@RequestMapping("/api/v1/admin/cases")
@Profile("!dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class CaseAdminController {
    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";

    private final CaseHttpSupport support;
    private final ObjectProvider<CaseLifecycleStore> store;
    private final ObjectProvider<TradeApplication> trades;
    private final ObjectProvider<ReviewApplication> reviews;
    private final ObjectProvider<ReviewHttpSupport> reviewSupport;

    CaseAdminController(CaseHttpSupport support, ObjectProvider<CaseLifecycleStore> store,
                        ObjectProvider<ReviewApplication> reviews,
                        ObjectProvider<ReviewHttpSupport> reviewSupport, ObjectProvider<TradeApplication> trades) {
        this.support = support;
        this.store = store;
        this.reviews = reviews;
        this.reviewSupport = reviewSupport;
        this.trades = trades;
    }

    @GetMapping("/{case_id}/trade-history")
    ResponseEntity<JsonNode> tradeHistory(HttpServletRequest request,
                                          @PathVariable("case_id") String caseId) {
        long tradeId = support.queries().requireClaimedTrade(support.context(request), CaseIds.path(caseId));
        var application = trades.getIfAvailable();
        if (application == null) {
            throw CaseHttpSupport.unavailable();
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(application.caseHistory(tradeId));
    }

    @PostMapping("/{case_id}/claim")
    ResponseEntity<JsonNode> claim(HttpServletRequest request,
                                   @PathVariable("case_id") String caseId,
                                   @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        long id = CaseIds.path(caseId);
        String idempotency = idempotency(key);
        var lifecycle = store.getIfAvailable();
        var facts = lifecycle == null ? java.util.Optional.<io.github.iy88.project1.casemanagement.application.CaseRecords.Facts>empty()
                : lifecycle.find(id);
        if (facts.isPresent() && CaseVocabulary.PRODUCT_REVIEW.equals(facts.get().caseType())) {
            var review = reviews.getIfAvailable();
            var identity = reviewSupport.getIfAvailable();
            if (review == null || identity == null) {
                throw CaseHttpSupport.unavailable();
            }
            // Review cases keep their own claim authority and identity adapter (S2-01).
            return write(review.claim(identity.context(request), idempotency, id));
        }
        return write(support.application().claim(support.context(request), idempotency, id));
    }

    @PostMapping("/{case_id}/evidence")
    ResponseEntity<JsonNode> referenceEvidence(HttpServletRequest request,
                                               @PathVariable("case_id") String caseId,
                                               @RequestBody(required = false) CaseRequests.EvidenceReference body,
                                               @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().referenceEvidence(context, idempotency(key), CaseIds.path(caseId),
                CaseIds.evidenceReference(body)));
    }

    @GetMapping("/{case_id}/evidence/{evidence_id}")
    ResponseEntity<JsonNode> referencedEvidence(HttpServletRequest request,
                                                @PathVariable("case_id") String caseId,
                                                @PathVariable("evidence_id") String evidenceId) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(support.queries().referencedEvidence(support.context(request), CaseIds.path(caseId),
                        CaseIds.path(evidenceId)));
    }

    @PostMapping("/{case_id}/inquiries")
    ResponseEntity<JsonNode> inquire(HttpServletRequest request,
                                     @PathVariable("case_id") String caseId,
                                     @RequestBody(required = false) CaseRequests.Inquiry body,
                                     @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().inquire(context, idempotency(key), CaseIds.path(caseId),
                CaseIds.inquiry(body)));
    }

    @PostMapping("/{case_id}/decisions")
    ResponseEntity<JsonNode> decide(HttpServletRequest request,
                                    @PathVariable("case_id") String caseId,
                                    @RequestBody(required = false) CaseRequests.Decision body,
                                    @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().decide(context, idempotency(key), CaseIds.path(caseId),
                CaseIds.decision(body)));
    }

    @PostMapping("/{case_id}/close")
    ResponseEntity<JsonNode> close(HttpServletRequest request,
                                   @PathVariable("case_id") String caseId,
                                   @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().close(context, idempotency(key), CaseIds.path(caseId)));
    }

    @PostMapping("/{case_id}/publish-result")
    ResponseEntity<JsonNode> publish(HttpServletRequest request,
                                     @PathVariable("case_id") String caseId,
                                     @RequestBody(required = false) CaseRequests.Publish body,
                                     @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        return write(support.application().publish(context, idempotency(key), CaseIds.path(caseId),
                CaseIds.publish(body)));
    }

    @PostMapping("/{case_id}/enforcements/{enforcement_id}/lift")
    ResponseEntity<JsonNode> lift(HttpServletRequest request,
                                  @PathVariable("case_id") String caseId,
                                  @PathVariable("enforcement_id") String enforcementId,
                                  @RequestBody(required = false) CaseRequests.Lift body,
                                  @RequestHeader(name = IDEMPOTENCY_HEADER, required = false) String key) {
        var context = support.context(request);
        String reason = body == null ? null : body.reason();
        return write(support.application().lift(context, idempotency(key), CaseIds.path(caseId),
                enforcementId, reason));
    }

    private static ResponseEntity<JsonNode> write(WriteResult<?> result) {
        return ResponseEntity.status(result.status()).cacheControl(CacheControl.noStore())
                .body((JsonNode) result.data());
    }

    private static String idempotency(String value) {
        if (value == null || value.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "缺少 Idempotency-Key");
        }
        return value;
    }
}
