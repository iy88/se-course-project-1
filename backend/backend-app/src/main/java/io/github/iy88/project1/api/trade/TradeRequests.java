package io.github.iy88.project1.api.trade;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;

/** HTTP request bodies. Trade JSON names follow the public contract. */
public final class TradeRequests {
    private TradeRequests() {
    }

    public record PurchaseRequest(String note, @JsonProperty("expected_product_version") Integer expectedProductVersion) {
    }

    public record Versioned(@JsonProperty("expected_version") Integer expectedVersion) {
    }

    public record Reject(String reason, @JsonProperty("expected_version") Integer expectedVersion) {
    }

    public record Agreement(
            @JsonProperty("delivery_at") Instant deliveryAt,
            @JsonProperty("delivery_place_text") String deliveryPlaceText,
            @JsonProperty("delivery_method") String deliveryMethod,
            @JsonProperty("amount_cents") Long amountCents,
            @JsonProperty("payment_method") String paymentMethod,
            @JsonProperty("payment_timing") String paymentTiming,
            @JsonProperty("base_agreement_id") String baseAgreementId,
            @JsonProperty("expected_version") Integer expectedVersion) {
    }

    public record Decision(String decision, @JsonProperty("expected_version") Integer expectedVersion) {
    }

    public record Confirmation(String note, @JsonProperty("expected_version") Integer expectedVersion) {
    }

    public record Cancellation(String reason, @JsonProperty("expected_version") Integer expectedVersion) {
    }

    public record Dispute(String statement, @JsonProperty("expected_version") Integer expectedVersion) {
    }
}
