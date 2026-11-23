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

    protected ProductCategory() {
    }

    public ProductCategory(long productId, long categoryId, long sellerId, Instant now) {
        this.productId = productId;
        this.categoryId = categoryId;
        this.source = "seller";
        this.createdByKind = "seller";
        this.createdById = sellerId;
        this.createdAt = now;
    }

    public long productId() { return productId; }
    public long categoryId() { return categoryId; }
    public boolean active() { return removedAt == null; }

    public void remove(Instant now, String kind, long actorId) {
        if (removedAt == null) {
            removedAt = now;
            removedByKind = kind;
            removedById = actorId;
        }
    }
}
