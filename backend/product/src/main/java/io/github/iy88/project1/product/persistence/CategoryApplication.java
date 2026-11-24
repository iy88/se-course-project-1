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
    public String proposedName() { return proposedName; }
    public String status() { return status; }

    public void withdraw(Instant now) {
        if ("pending".equals(status)) {
            status = "withdrawn";
        }
    }
}
