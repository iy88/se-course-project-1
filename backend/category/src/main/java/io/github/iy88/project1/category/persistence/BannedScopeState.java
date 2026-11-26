package io.github.iy88.project1.category.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "banned_scope_state")
public class BannedScopeState {
    @Id
    @Column(name = "singleton")
    private Boolean singleton;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected BannedScopeState() {
    }

    public void touch(Instant now) {
        updatedAt = now;
    }
}
