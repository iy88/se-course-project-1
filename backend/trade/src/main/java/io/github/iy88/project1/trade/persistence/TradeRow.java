package io.github.iy88.project1.trade.persistence;

import io.github.iy88.project1.trade.domain.TradeStatus;
import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Convert;
import jakarta.persistence.Converter;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "trade")
class TradeRow {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private long productId;
    private long buyerId;
    private long sellerId;
    @Convert(converter = TradeRow.StatusConverter.class)
    private TradeStatus status;
    private String requestNote;
    private Long activeAgreementId;
    private int version;
    private String closeReason;
    private String terminalReason;
    private Instant requestedAt;
    private Instant respondedAt;
    private Instant endedAt;
    private Instant createdAt;
    private Instant updatedAt;

    protected TradeRow() {}

    TradeRow(long productId, long buyerId, long sellerId, String requestNote, Instant now) {
        this.productId = productId;
        this.buyerId = buyerId;
        this.sellerId = sellerId;
        this.status = TradeStatus.PENDING_ACCEPTANCE;
        this.requestNote = requestNote;
        this.version = 1;
        this.requestedAt = now;
        this.createdAt = now;
        this.updatedAt = now;
    }

    long id() {
        return id;
    }

    @Converter
    public static class StatusConverter implements AttributeConverter<TradeStatus, String> {
        @Override
        public String convertToDatabaseColumn(TradeStatus status) {
            return status == null ? null : status.value();
        }

        @Override
        public TradeStatus convertToEntityAttribute(String value) {
            return value == null ? null : TradeStatus.from(value);
        }
    }
}
