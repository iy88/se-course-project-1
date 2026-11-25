package io.github.iy88.project1.category.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "category_name")
public class CategoryName {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "category_name_id")
    private Long id;

    @Column(name = "category_id", nullable = false)
    private long categoryId;

    @Column(nullable = false)
    private String name;

    @Column(name = "name_kind", nullable = false)
    private String nameKind;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "deactivated_at")
    private Instant deactivatedAt;

    protected CategoryName() {
    }

    public CategoryName(long categoryId, String name, String nameKind, Instant createdAt) {
        this.categoryId = categoryId;
        this.name = name;
        this.nameKind = nameKind;
        this.createdAt = createdAt;
    }

    public long id() { return id; }
    public long categoryId() { return categoryId; }
    public String name() { return name; }
    public String nameKind() { return nameKind; }
    public boolean active() { return deactivatedAt == null; }

    public void toAlias() {
        nameKind = "alias";
    }

    public void deactivate(Instant now) {
        if (deactivatedAt == null) {
            deactivatedAt = now;
        }
    }
}
