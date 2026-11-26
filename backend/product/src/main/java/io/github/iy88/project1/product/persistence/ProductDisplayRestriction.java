package io.github.iy88.project1.product.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * Read-side mapping used by the public product query. Writes stay in the explicit SQL of
 * {@code ProductDisplayRestrictions}, so this entity has no lifecycle or occupancy fields.
 */
@Entity
@Table(name = "product_display_restriction")
public class ProductDisplayRestriction {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "restriction_id")
    private Long id;

    @Column(name = "product_id", nullable = false)
    private long productId;

    @Column(name = "source_type", nullable = false)
    private String sourceType;

    @Column(name = "source_ref_id", nullable = false)
    private long sourceRefId;

    @Column(nullable = false)
    private String reason;

    @Column(name = "basis_ref", nullable = false)
    private String basisRef;

    @Column(name = "created_by", nullable = false)
    private long createdBy;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "released_at")
    private Instant releasedAt;

    @Column(name = "released_by")
    private Long releasedBy;

    @Column(name = "release_reason")
    private String releaseReason;

    @Column(name = "release_basis_ref")
    private String releaseBasisRef;

    protected ProductDisplayRestriction() {
    }

    public boolean active() {
        return releasedAt == null;
    }
}
