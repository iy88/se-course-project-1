package io.github.iy88.project1.product.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "product_audit")
public class ProductAudit {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "audit_id")
    private Long id;

    @Column(name = "product_id", nullable = false)
    private long productId;

    @Column(name = "sequence_no", nullable = false)
    private int sequenceNo;

    @Column(name = "case_id", nullable = false)
    private long caseId;

    @Column(nullable = false)
    private String status;

    @Column(name = "submitted_at", nullable = false)
    private Instant submittedAt;

    @Column(name = "decided_by_admin_id")
    private Long decidedByAdminId;

    @Column(name = "decided_at")
    private Instant decidedAt;

    @Column(name = "decision_reason")
    private String decisionReason;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "reviewed_content")
    private Map<String, Object> reviewedContent;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "reviewed_application")
    private Map<String, Object> reviewedApplication;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "reviewed_banned_item_ids", nullable = false)
    private List<Long> reviewedBannedItemIds;

    @Column(name = "withdrawn_at")
    private Instant withdrawnAt;

    protected ProductAudit() {
    }

    public ProductAudit(long productId, int sequenceNo, long caseId, Instant now) {
        this.productId = productId;
        this.sequenceNo = sequenceNo;
        this.caseId = caseId;
        this.status = "pending";
        this.submittedAt = now;
        this.reviewedBannedItemIds = List.of();
    }

    public long id() { return id; }
    public long productId() { return productId; }
    public int sequenceNo() { return sequenceNo; }
    public long caseId() { return caseId; }
    public String status() { return status; }
    public Instant submittedAt() { return submittedAt; }
    public Long decidedByAdminId() { return decidedByAdminId; }
    public String decisionReason() { return decisionReason; }
    public Instant decidedAt() { return decidedAt; }
    public Map<String, Object> reviewedContent() { return reviewedContent; }
    public Map<String, Object> reviewedApplication() { return reviewedApplication; }
    public List<Long> reviewedBannedItemIds() { return reviewedBannedItemIds; }
    public Instant withdrawnAt() { return withdrawnAt; }

    /** Content version covered by the latest decision snapshot; null before a decision is saved. */
    public Integer reviewedContentVersion() {
        Object value = reviewedContent == null ? null : reviewedContent.get("content_version");
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text) {
            try {
                return Integer.valueOf(text);
            } catch (NumberFormatException invalid) {
                return null;
            }
        }
        return null;
    }

    public void decide(long adminId, boolean approved, String reason, Map<String, Object> content,
                       Map<String, Object> application, List<Long> bannedItemIds, Instant now) {
        if (!"pending".equals(status)) {
            throw new IllegalStateException("Only a pending product audit can be decided");
        }
        if (adminId <= 0 || now == null) {
            throw new IllegalArgumentException("Invalid product review decision");
        }
        status = approved ? "passed" : "rejected";
        decidedByAdminId = adminId;
        decidedAt = now;
        decisionReason = reason;
        reviewedContent = content;
        reviewedApplication = application;
        reviewedBannedItemIds = bannedItemIds == null ? List.of() : List.copyOf(bannedItemIds);
    }

    public void withdraw(Instant now) {
        if ("pending".equals(status)) {
            status = "withdrawn";
            withdrawnAt = now;
        }
    }
}
