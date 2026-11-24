package io.github.iy88.project1.product.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "category_application")
public class CategoryApplication {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "application_id")
    private Long id;

    @Column(name = "product_id", nullable = false)
    private long productId;

    @Column(name = "submitted_by_account_id", nullable = false)
    private long submittedByAccountId;

    @Column(name = "proposed_name", nullable = false)
    private String proposedName;

    @Column(nullable = false)
    private String status;

    @Column
    private String resolution;

    @Column(name = "resolved_category_id")
    private Long resolvedCategoryId;

    @Column(name = "decided_by_admin_id")
    private Long decidedByAdminId;

    @Column(name = "decided_at")
    private Instant decidedAt;

    @Column(name = "rejection_reason")
    private String rejectionReason;

    @Column(nullable = false)
    private Instant createdAt;

    protected CategoryApplication() {
    }

    public CategoryApplication(long productId, long submittedByAccountId, String proposedName, Instant now) {
        this.productId = productId;
        this.submittedByAccountId = submittedByAccountId;
        this.proposedName = proposedName;
        this.status = "pending";
        this.createdAt = now;
    }

    public long id() { return id; }
    public long productId() { return productId; }
    public String proposedName() { return proposedName; }
    public String status() { return status; }
    public String resolution() { return resolution; }
    public Long resolvedCategoryId() { return resolvedCategoryId; }
    public Long decidedByAdminId() { return decidedByAdminId; }
    public Instant decidedAt() { return decidedAt; }
    public String rejectionReason() { return rejectionReason; }

    public void approve(long adminId, long categoryId, String resolution, Instant now) {
        requirePending();
        this.status = "approved";
        this.resolution = resolution;
        this.resolvedCategoryId = categoryId;
        this.decidedByAdminId = adminId;
        this.decidedAt = now;
    }

    public void reject(long adminId, String reason, Instant now) {
        requirePending();
        this.status = "rejected";
        this.decidedByAdminId = adminId;
        this.decidedAt = now;
        this.rejectionReason = reason;
    }

    public void withdraw(Instant now) {
        if ("pending".equals(status)) {
            status = "withdrawn";
        }
    }

    private void requirePending() {
        if (!"pending".equals(status)) {
            throw new IllegalStateException("Only a pending category application can be decided");
        }
    }
}
