package io.github.iy88.project1.product.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "product_category")
public class ProductCategory {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "product_category_id")
    private Long id;

    @Column(name = "product_id", nullable = false)
    private long productId;

    @Column(name = "category_id", nullable = false)
    private long categoryId;

    @Column(nullable = false)
    private String source;

    @Column(name = "created_by_kind", nullable = false)
    private String createdByKind;

    @Column(name = "created_by_id", nullable = false)
    private long createdById;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "removed_at")
    private Instant removedAt;

    @Column(name = "removed_by_kind")
    private String removedByKind;

    @Column(name = "removed_by_id")
    private Long removedById;

    @Column(name = "change_basis_type")
    private String changeBasisType;

    @Column(name = "change_basis_id")
    private Long changeBasisId;

    protected ProductCategory() {
    }

    public ProductCategory(long productId, long categoryId, long sellerId, Instant now) {
        this(productId, categoryId, "seller", "seller", sellerId, now);
    }

    public ProductCategory(long productId, long categoryId, String source, String createdByKind,
                           long createdById, Instant now) {
        this(productId, categoryId, source, createdByKind, createdById, null, null, now);
    }

    /** Relation created by an administrator correction; the basis names the case it relies on. */
    public static ProductCategory adminCorrection(long productId, long categoryId, long managerId,
                                                  String basisType, long basisId, Instant now) {
        return new ProductCategory(productId, categoryId, "admin_correction", "admin", managerId, basisType,
                basisId, now);
    }

    private ProductCategory(long productId, long categoryId, String source, String createdByKind,
                            long createdById, String changeBasisType, Long changeBasisId, Instant now) {
        this.productId = productId;
        this.categoryId = categoryId;
        this.source = source;
        this.createdByKind = createdByKind;
        this.createdById = createdById;
        this.changeBasisType = changeBasisType;
        this.changeBasisId = changeBasisId;
        this.createdAt = now;
    }

    public long productId() { return productId; }
    public long categoryId() { return categoryId; }
    public String source() { return source; }
    public boolean active() { return removedAt == null; }

    public void remove(Instant now, String kind, long actorId) {
        if (removedAt == null) {
            removedAt = now;
            removedByKind = kind;
            removedById = actorId;
        }
    }
}
