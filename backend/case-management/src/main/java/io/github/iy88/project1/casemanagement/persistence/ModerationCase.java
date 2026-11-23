package io.github.iy88.project1.casemanagement.persistence;

import io.github.iy88.project1.casemanagement.application.CaseClaim;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "moderation_case")
class ModerationCase {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "case_type", nullable = false)
    private String caseType;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "claimed_manager_id")
    private Long claimedManagerId;

    @Column(name = "claimed_at")
    private Instant claimedAt;

    protected ModerationCase() {
    }

    ModerationCase(String caseType, Instant createdAt) {
        this.caseType = caseType;
        this.createdAt = createdAt;
    }

    long id() {
        return id;
    }

    void claim(long managerId, Instant claimedAt) {
        if (claimedManagerId != null) {
            throw new IllegalStateException("Case is already claimed");
        }
        this.claimedManagerId = managerId;
        this.claimedAt = claimedAt;
    }

    CaseClaim snapshot() {
        return new CaseClaim(id, caseType, createdAt, claimedManagerId, claimedAt);
    }
}
