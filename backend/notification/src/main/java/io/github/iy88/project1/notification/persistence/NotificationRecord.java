package io.github.iy88.project1.notification.persistence;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import io.github.iy88.project1.core.ResourceRef;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.Map;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * Persisted notification fact.
 *
 * The rendered summary is deliberately absent: it belongs to the source module and
 * is produced per reader at query time.
 */
@Entity
@Table(name = "notification")
class NotificationRecord {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "notification_id")
    private Long id;
    private long recipientAccountId;
    private String intentKey;
    private String eventType;
    private java.util.UUID businessEventId;
    private String sourceType;
    private long sourceId;
    private String templateKey;
    private String templateVersion;
    @JdbcTypeCode(SqlTypes.JSON)
    private DisplayParams displayParams;
    private Instant occurredAt;
    private Instant createdAt;
    private Instant readAt;

    protected NotificationRecord() {}

    NotificationRecord(long recipientAccountId, String intentKey, String eventType,
                       java.util.UUID businessEventId, ResourceRef source, String templateKey,
                       String templateVersion, Map<String, String> displayParams, Instant occurredAt,
                       Instant createdAt) {
        this.recipientAccountId = recipientAccountId;
        this.intentKey = intentKey;
        this.eventType = eventType;
        this.businessEventId = businessEventId;
        this.sourceType = source.type();
        this.sourceId = source.id();
        this.templateKey = templateKey;
        this.templateVersion = templateVersion;
        this.displayParams = new DisplayParams(displayParams);
        this.occurredAt = occurredAt;
        this.createdAt = createdAt;
    }

    /** First read only; a later call keeps the stored instant. */
    void markRead(Instant at) {
        if (readAt == null) {
            readAt = at;
        }
    }

    NotificationStore.Stored snapshot() {
        return new NotificationStore.Stored(id, recipientAccountId, intentKey, eventType,
                new ResourceRef(sourceType, sourceId), templateKey, templateVersion,
                displayParams.values(), occurredAt, createdAt, readAt);
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record DisplayParams(Map<String, String> values) {
        DisplayParams {
            values = values == null ? Map.of() : Map.copyOf(values);
        }
    }
}
