package io.github.iy88.project1.account.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "session_revocation")
public class SessionRevocation {
    @Id
    @Column(name = "session_id")
    private UUID sessionId;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "next_attempt_at", nullable = false)
    private Instant nextAttemptAt;

    @Column(nullable = false)
    private int attempts;

    @Column(name = "completed_at")
    private Instant completedAt;

    protected SessionRevocation() {
    }

    public SessionRevocation(UUID sessionId, Instant now) {
        this.sessionId = sessionId;
        this.createdAt = now;
        this.nextAttemptAt = now;
        this.attempts = 0;
    }

    public UUID sessionId() { return sessionId; }

    public void complete(Instant now) {
        completedAt = now;
    }
}
