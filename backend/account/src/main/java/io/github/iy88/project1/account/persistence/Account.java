package io.github.iy88.project1.account.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "account")
public class Account {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "account_id")
    private Long id;

    @Column(nullable = false)
    private String email;

    @Column(name = "display_name", nullable = false)
    private String displayName;

    @Column(name = "password_hash", nullable = false)
    private String passwordHash;

    @Column(name = "credential_version", nullable = false)
    private int credentialVersion;

    @Column(nullable = false)
    private String role;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected Account() {
    }

    public Account(String email, String displayName, String passwordHash, Instant createdAt) {
        this.email = email;
        this.displayName = displayName;
        this.passwordHash = passwordHash;
        this.credentialVersion = 1;
        this.role = "user";
        this.createdAt = createdAt;
    }

    public long id() { return id; }
    public String email() { return email; }
    public String displayName() { return displayName; }
    public String passwordHash() { return passwordHash; }
    public int credentialVersion() { return credentialVersion; }
    public String role() { return role; }
    public Instant createdAt() { return createdAt; }

    public void rename(String displayName) {
        this.displayName = displayName;
    }

    public void replacePassword(String passwordHash) {
        this.passwordHash = passwordHash;
        this.credentialVersion++;
    }

    public void changeEmail(String email) {
        this.email = email;
        this.credentialVersion++;
    }
}
