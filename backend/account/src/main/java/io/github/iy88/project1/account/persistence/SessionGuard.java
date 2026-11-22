package io.github.iy88.project1.account.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "session_guard")
public class SessionGuard {
    @Id
    @Column(name = "session_id")
    private UUID id;

    @Column(name = "token_digest", nullable = false)
    private byte[] tokenDigest;

    @Column(name = "account_id", nullable = false)
    private long accountId;

    @Column(name = "credential_version", nullable = false)
    private int credentialVersion;

    @Column(name = "issued_at", nullable = false)
    private Instant issuedAt;

    @Column(name = "absolute_expires_at", nullable = false)
    private Instant absoluteExpiresAt;

    @Column(name = "idle_timeout_seconds", nullable = false)
    private int idleTimeoutSeconds;

    @Column(name = "renew_interval_seconds", nullable = false)
    private int renewIntervalSeconds;

    @Column(name = "csrf_digest", nullable = false)
    private byte[] csrfDigest;

    @Column(name = "revoked_at")
    private Instant revokedAt;

    protected SessionGuard() {
    }

    public SessionGuard(UUID id, byte[] tokenDigest, long accountId, int credentialVersion, Instant issuedAt,
                        Instant absoluteExpiresAt, int idleTimeoutSeconds, int renewIntervalSeconds,
                        byte[] csrfDigest) {
        this.id = id;
        this.tokenDigest = tokenDigest;
        this.accountId = accountId;
        this.credentialVersion = credentialVersion;
        this.issuedAt = issuedAt;
        this.absoluteExpiresAt = absoluteExpiresAt;
        this.idleTimeoutSeconds = idleTimeoutSeconds;
        this.renewIntervalSeconds = renewIntervalSeconds;
        this.csrfDigest = csrfDigest;
    }

    public UUID id() { return id; }
    public byte[] tokenDigest() { return tokenDigest; }
    public long accountId() { return accountId; }
    public int credentialVersion() { return credentialVersion; }
    public Instant issuedAt() { return issuedAt; }
    public Instant absoluteExpiresAt() { return absoluteExpiresAt; }
    public int idleTimeoutSeconds() { return idleTimeoutSeconds; }
    public int renewIntervalSeconds() { return renewIntervalSeconds; }
    public byte[] csrfDigest() { return csrfDigest; }
    public Instant revokedAt() { return revokedAt; }
    public boolean revoked() { return revokedAt != null; }

    public boolean revoke(Instant now) {
        if (revokedAt != null) {
            return false;
        }
        revokedAt = now;
        return true;
    }
}
