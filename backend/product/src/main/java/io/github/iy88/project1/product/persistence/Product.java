package io.github.iy88.project1.product.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "product")
public class Product {
    public static final String PENDING_REVIEW = "pending_review";
    public static final String REVIEW_REJECTED = "review_rejected";
    public static final String PUBLIC = "public";
    public static final String IN_TRADE = "in_trade";
    public static final String OFF_SHELF = "off_shelf";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "product_id")
    private Long id;

    @Column(name = "seller_account_id", nullable = false)
    private long sellerAccountId;

    @Column(nullable = false)
    private String title;

    @Column(nullable = false)
    private String description;

    @Column(name = "price_cents", nullable = false)
    private long priceCents;

    @Column(name = "lifecycle_state", nullable = false)
    private String lifecycleState;

    @Column(name = "occupied_by_trade_id")
    private Long occupiedByTradeId;

    @Column(name = "content_version", nullable = false)
    private int contentVersion;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    protected Product() {
    }

    public Product(long sellerAccountId, String title, String description, long priceCents, Instant now) {
        this.sellerAccountId = sellerAccountId;
        this.title = title;
        this.description = description;
        this.priceCents = priceCents;
        this.lifecycleState = PENDING_REVIEW;
        this.contentVersion = 1;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public long id() { return id; }
    public long sellerAccountId() { return sellerAccountId; }
    public String title() { return title; }
    public String description() { return description; }
    public long priceCents() { return priceCents; }
    public String lifecycleState() { return lifecycleState; }
    public Long occupiedByTradeId() { return occupiedByTradeId; }
    public int contentVersion() { return contentVersion; }
    public Instant createdAt() { return createdAt; }
    public Instant updatedAt() { return updatedAt; }
    public Instant deletedAt() { return deletedAt; }
    public boolean deleted() { return deletedAt != null; }

    public void editContent(String title, String description, long priceCents, Instant now) {
        this.title = title;
        this.description = description;
        this.priceCents = priceCents;
        this.contentVersion++;
        this.updatedAt = now;
    }

    public void touchContentVersion(Instant now) {
        this.contentVersion++;
        this.updatedAt = now;
    }

    public void transition(String state, Instant now) {
        this.lifecycleState = state;
        this.updatedAt = now;
    }
}
