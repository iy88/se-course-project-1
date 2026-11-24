package io.github.iy88.project1.category.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "category")
public class Category {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "category_id")
    private Long id;

    @Column(name = "created_by_admin_id", nullable = false)
    private long createdByAdminId;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "disabled_at")
    private Instant disabledAt;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    protected Category() {
    }

    public Category(long createdByAdminId, Instant createdAt) {
        this.createdByAdminId = createdByAdminId;
        this.createdAt = createdAt;
    }

    public long id() { return id; }
    public Instant createdAt() { return createdAt; }
    public Instant disabledAt() { return disabledAt; }
    public Instant deletedAt() { return deletedAt; }
    public boolean deleted() { return deletedAt != null; }
    public boolean disabled() { return disabledAt != null; }

    public String state() {
        if (deletedAt != null) {
            return "deleted";
        }
        return disabledAt == null ? "active" : "disabled";
    }

    public void disable(Instant now) {
        if (disabledAt == null) {
            disabledAt = now;
        }
    }

    public void delete(Instant now) {
        if (deletedAt == null) {
            deletedAt = now;
        }
    }
}
