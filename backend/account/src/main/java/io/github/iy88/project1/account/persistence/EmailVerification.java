package io.github.iy88.project1.account.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "email_verification")
public class EmailVerification {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(nullable = false)
    private String purpose;

    @Column(nullable = false)
    private String email;

    @Column(name = "account_id")
    private Long accountId;

    @Column(name = "entry_digest")
    private byte[] entryDigest;

    @Column(name = "group_id", nullable = false)
    private UUID groupId;

    @Column(name = "credential_version")
    private Integer credentialVersion;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at", nullable = false)
    private Instant expiresAt;

    @Column(name = "code")
    private String code;

    @Column(name = "code_length", nullable = false)
    private int codeLength;

    @Column(name = "max_failed_attempts", nullable = false)
    private int maxFailedAttempts;

    @Column(name = "rule_version", nullable = false)
    private String ruleVersion;

    @Column(name = "failed_attempts", nullable = false)
    private int failedAttempts;

    @Column(name = "consumed_at")
    private Instant consumedAt;

    @Column(name = "invalidated_at")
    private Instant invalidatedAt;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "delivery_rules", nullable = false)
    private Map<String, Object> deliveryRules;

    @Column(name = "send_attempts", nullable = false)
    private int sendAttempts;

    @Column(name = "next_attempt_at", nullable = false)
    private Instant nextAttemptAt;

    @Column(name = "lease_token")
    private UUID leaseToken;

    @Column(name = "lease_until")
    private Instant leaseUntil;

    @Column(name = "sent_at")
    private Instant sentAt;

    @Column(name = "last_delivery_error")
    private String lastDeliveryError;

    protected EmailVerification() {
    }

    public EmailVerification(String purpose, String email, Long accountId, byte[] entryDigest, UUID groupId,
                             Integer credentialVersion, Instant createdAt, Instant expiresAt, String code,
                             int codeLength, int maxFailedAttempts, String ruleVersion,
                             Map<String, Object> deliveryRules, Instant nextAttemptAt) {
        this.purpose = purpose;
        this.email = email;
        this.accountId = accountId;
        this.entryDigest = entryDigest;
        this.groupId = groupId;
        this.credentialVersion = credentialVersion;
        this.createdAt = createdAt;
        this.expiresAt = expiresAt;
        this.code = code;
        this.codeLength = codeLength;
        this.maxFailedAttempts = maxFailedAttempts;
        this.ruleVersion = ruleVersion;
        this.failedAttempts = 0;
        this.deliveryRules = deliveryRules;
        this.sendAttempts = 0;
        this.nextAttemptAt = nextAttemptAt;
    }

    public long id() { return id; }
    public String purpose() { return purpose; }
    public String email() { return email; }
    public Long accountId() { return accountId; }
    public byte[] entryDigest() { return entryDigest; }
    public String code() { return code; }
    public Instant expiresAt() { return expiresAt; }
    public int failedAttempts() { return failedAttempts; }
    public boolean consumed() { return consumedAt != null; }
    public boolean invalidated() { return invalidatedAt != null; }

    public boolean usable(Instant now) {
        return code != null && consumedAt == null && invalidatedAt == null && now.isBefore(expiresAt);
    }

    public boolean matches(String submitted) {
        if (code == null || submitted == null) {
            return false;
        }
        return MessageDigest.isEqual(code.getBytes(StandardCharsets.UTF_8), submitted.getBytes(StandardCharsets.UTF_8));
    }

    public void recordFailure(Instant now) {
        failedAttempts++;
        if (failedAttempts >= maxFailedAttempts) {
            invalidate(now);
        }
    }

    public void consume(Instant now) {
        consumedAt = now;
        code = null;
    }

    public void invalidate(Instant now) {
        if (consumedAt != null || invalidatedAt != null) {
            return;
        }
        invalidatedAt = now;
        code = null;
    }

    public void markSent(Instant now) {
        sentAt = now;
        sendAttempts++;
        leaseToken = null;
        leaseUntil = null;
    }
}
