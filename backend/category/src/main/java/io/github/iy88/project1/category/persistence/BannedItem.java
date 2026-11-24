package io.github.iy88.project1.category.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "banned_item")
public class BannedItem {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "banned_item_id")
    private Long id;

    @Column(name = "item_group", nullable = false)
    private String group;

    @Column(nullable = false)
    private String content;

    @Column(name = "display_order", nullable = false)
    private int displayOrder;

    @Column(name = "updated_by_admin_id", nullable = false)
    private long updatedByAdminId;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Column(name = "deleted_at")
    private Instant deletedAt;

    protected BannedItem() {
    }

    public BannedItem(String group, String content, int displayOrder, long adminId, Instant now) {
        this.group = group;
        this.content = content;
        this.displayOrder = displayOrder;
        this.updatedByAdminId = adminId;
        this.updatedAt = now;
    }

    public long id() { return id; }
    public String group() { return group; }
    public String content() { return content; }
    public int displayOrder() { return displayOrder; }
    public Instant updatedAt() { return updatedAt; }
    public boolean deleted() { return deletedAt != null; }

    public void update(String group, String content, int displayOrder, long adminId, Instant now) {
        this.group = group;
        this.content = content;
        this.displayOrder = displayOrder;
        this.updatedByAdminId = adminId;
        this.updatedAt = now;
    }

    public void delete(Instant now) {
        if (deletedAt == null) {
            deletedAt = now;
        }
    }
}
