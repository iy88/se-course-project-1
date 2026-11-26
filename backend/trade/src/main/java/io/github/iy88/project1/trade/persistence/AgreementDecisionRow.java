package io.github.iy88.project1.trade.persistence;

import io.github.iy88.project1.trade.domain.TradeModels;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "agreement_decision")
class AgreementDecisionRow {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private long agreementId;
    private String decision;
    private long actorId;
    private Instant decidedAt;
    private UUID businessEventId;

    protected AgreementDecisionRow() {}

    AgreementDecisionRow(TradeModels.Decision decision) {
        this.agreementId = decision.agreementId();
        this.decision = decision.decision().value();
        this.actorId = decision.actorId();
        this.decidedAt = decision.decidedAt();
        this.businessEventId = decision.businessEventId();
    }

    long id() {
        return id;
    }
}
