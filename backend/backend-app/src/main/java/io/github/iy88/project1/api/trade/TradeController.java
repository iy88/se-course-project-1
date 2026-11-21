package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.trade.application.TradeApplication;
import io.github.iy88.project1.trade.application.TradeCommands;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
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

@RestController
@RequestMapping("/api/v1")
@Profile("infrastructure & !dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
public class TradeController {
    private final TradeApplication trades;
    private final ApiRequestContext requests;
    private final TradeActorResolver actors;

    public TradeController(TradeApplication trades, ApiRequestContext requests, TradeActorResolver actors) {
        this.trades = trades;
        this.requests = requests;
        this.actors = actors;
    }

    @PostMapping("/products/{product_id}/purchase-requests")
    public ResponseEntity<JsonNode> createPurchaseRequest(
            @PathVariable("product_id") long productId,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody TradeRequests.PurchaseRequest body,
            HttpServletRequest request) {
        var result = trades.createPurchaseRequest(context(request), key,
                new TradeCommands.CreatePurchaseRequest(productId, body.note(),
                        required(body.expectedProductVersion(), "expected_product_version")));
        return created(result, URI.create("/api/v1/trades/" + result.data().path("id").stringValue()));
    }

    @PostMapping("/trades/{trade_id}/accept")
    public ResponseEntity<JsonNode> accept(@PathVariable("trade_id") long tradeId,
                                           @RequestHeader("Idempotency-Key") String key,
                                           @RequestBody TradeRequests.Versioned body,
                                           HttpServletRequest request) {
        return respond(trades.accept(context(request), key, versioned(tradeId, body)));
    }

    @PostMapping("/trades/{trade_id}/reject")
    public ResponseEntity<JsonNode> reject(@PathVariable("trade_id") long tradeId,
                                           @RequestHeader("Idempotency-Key") String key,
                                           @RequestBody TradeRequests.Reject body,
                                           HttpServletRequest request) {
        return respond(trades.reject(context(request), key, new TradeCommands.Reject(tradeId, body.reason(),
                required(body.expectedVersion(), "expected_version"))));
    }

    @PostMapping("/trades/{trade_id}/withdraw")
    public ResponseEntity<JsonNode> withdraw(@PathVariable("trade_id") long tradeId,
                                             @RequestHeader("Idempotency-Key") String key,
                                             @RequestBody TradeRequests.Versioned body,
                                             HttpServletRequest request) {
        return respond(trades.withdraw(context(request), key, versioned(tradeId, body)));
    }

    @PostMapping("/trades/{trade_id}/agreements")
    public ResponseEntity<JsonNode> proposeAgreement(@PathVariable("trade_id") long tradeId,
                                                     @RequestHeader("Idempotency-Key") String key,
                                                     @RequestBody TradeRequests.Agreement body,
                                                     HttpServletRequest request) {
        Long base = body.baseAgreementId() == null || body.baseAgreementId().isBlank() ? null
                : id(body.baseAgreementId(), "base_agreement_id");
        var command = new TradeCommands.ProposeAgreement(tradeId, body.deliveryAt(), body.deliveryPlaceText(),
                body.deliveryMethod(), body.amountCents() == null ? -1 : body.amountCents(),
                body.paymentMethod(), body.paymentTiming(), base,
                required(body.expectedVersion(), "expected_version"));
        return respond(trades.proposeAgreement(context(request), key, command));
    }

    @PostMapping("/trades/{trade_id}/agreements/{agreement_id}/decisions")
    public ResponseEntity<JsonNode> decideAgreement(@PathVariable("trade_id") long tradeId,
                                                    @PathVariable("agreement_id") long agreementId,
                                                    @RequestHeader("Idempotency-Key") String key,
                                                    @RequestBody TradeRequests.Decision body,
                                                    HttpServletRequest request) {
        return respond(trades.decideAgreement(context(request), key,
                new TradeCommands.DecideAgreement(tradeId, agreementId, body.decision(),
                        required(body.expectedVersion(), "expected_version"))));
    }

    @PostMapping("/trades/{trade_id}/completion-confirmations")
    public ResponseEntity<JsonNode> submitConfirmation(@PathVariable("trade_id") long tradeId,
                                                       @RequestHeader("Idempotency-Key") String key,
                                                       @RequestBody TradeRequests.Confirmation body,
                                                       HttpServletRequest request) {
        return respond(trades.submitConfirmation(context(request), key,
                new TradeCommands.ConfirmCompletion(tradeId, body.note(),
                        required(body.expectedVersion(), "expected_version"))));
    }

    @PostMapping("/trades/{trade_id}/cancellation-proposals")
    public ResponseEntity<JsonNode> proposeCancellation(@PathVariable("trade_id") long tradeId,
                                                        @RequestHeader("Idempotency-Key") String key,
                                                        @RequestBody TradeRequests.Cancellation body,
                                                        HttpServletRequest request) {
        return respond(trades.proposeCancellation(context(request), key,
                new TradeCommands.ProposeCancellation(tradeId, body.reason(),
                        required(body.expectedVersion(), "expected_version"))));
    }

    @PostMapping("/trades/{trade_id}/cancellation-proposals/{proposal_id}/decisions")
    public ResponseEntity<JsonNode> decideCancellation(@PathVariable("trade_id") long tradeId,
                                                       @PathVariable("proposal_id") long proposalId,
                                                       @RequestHeader("Idempotency-Key") String key,
                                                       @RequestBody TradeRequests.Decision body,
                                                       HttpServletRequest request) {
        return respond(trades.decideCancellation(context(request), key,
                new TradeCommands.DecideCancellation(tradeId, proposalId, body.decision(),
                        required(body.expectedVersion(), "expected_version"))));
    }

    @PostMapping("/trades/{trade_id}/disputes")
    public ResponseEntity<JsonNode> openDispute(@PathVariable("trade_id") long tradeId,
                                                @RequestHeader("Idempotency-Key") String key,
                                                @RequestBody TradeRequests.Dispute body,
                                                HttpServletRequest request) {
        return respond(trades.openDispute(context(request), key,
                new TradeCommands.OpenDispute(tradeId, body.statement(),
                        required(body.expectedVersion(), "expected_version"))));
    }

    @PostMapping("/trades/{trade_id}/disputes/{dispute_id}/resolution-confirmations")
    public ResponseEntity<JsonNode> confirmResolution(@PathVariable("trade_id") long tradeId,
                                                      @PathVariable("dispute_id") long disputeId,
                                                      @RequestHeader("Idempotency-Key") String key,
                                                      @RequestBody TradeRequests.Versioned body,
                                                      HttpServletRequest request) {
        return respond(trades.confirmResolution(context(request), key,
                new TradeCommands.ConfirmResolution(tradeId, disputeId,
                        required(body.expectedVersion(), "expected_version"))));
    }

    @GetMapping("/trades/{trade_id}")
    public JsonNode getTrade(@PathVariable("trade_id") long tradeId,
                             @RequestParam(value = "include", required = false) List<String> include,
                             HttpServletRequest request) {
        return trades.getTrade(context(request), tradeId, include == null ? List.of() : include);
    }

    @GetMapping("/me/trades")
    public JsonNode listMine(@RequestParam(value = "role", required = false) String role,
                             @RequestParam(value = "status", required = false) List<String> status,
                             @RequestParam(value = "page", required = false) Integer page,
                             @RequestParam(value = "page_size", required = false) Integer pageSize,
                             HttpServletRequest request) {
        return trades.listMine(context(request), role, status == null ? List.of() : status, page, pageSize);
    }

    private ExecutionContext context(HttpServletRequest request) {
        var actor = actors.resolve(request);
        return requests.forActor(request, ExecutionContext.ActorKind.ACCOUNT, Long.toString(actor.accountId()),
                actor.sessionId(), null, actor.credentialVersion());
    }

    private static TradeCommands.Versioned versioned(long tradeId, TradeRequests.Versioned body) {
        return new TradeCommands.Versioned(tradeId, required(body.expectedVersion(), "expected_version"));
    }

    private static ResponseEntity<JsonNode> respond(WriteResult<JsonNode> result) {
        return ResponseEntity.status(result.status()).body(result.data());
    }

    private static ResponseEntity<JsonNode> created(WriteResult<JsonNode> result, URI location) {
        return ResponseEntity.status(result.status()).location(location).body(result.data());
    }

    private static int required(Integer value, String field) {
        if (value == null) {
            throw new BusinessError("INPUT_INVALID", 422, field + " 不能为空");
        }
        return value;
    }

    private static long id(String value, String field) {
        try {
            long id = Long.parseLong(value);
            if (id <= 0 || !Long.toString(id).equals(value)) {
                throw new NumberFormatException();
            }
            return id;
        } catch (NumberFormatException invalid) {
            throw new BusinessError("INPUT_INVALID", 422, field + " 无效");
        }
    }
}
