package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.EmailVerification;
import io.github.iy88.project1.account.persistence.EmailVerificationRepository;
import io.github.iy88.project1.core.BusinessError;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class EmailVerificationService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Set<String> PURPOSES = Set.of("registration", "password_reset", "email_change");
    private static final String RULE_VERSION = "s2-v1";

    private final EmailVerificationRepository verifications;
    private final AccountRepository accounts;
    private final EmailRequestBudgetStore budget;
    private final AccountSettings settings;
    private final TransactionTemplate transaction;

    public EmailVerificationService(EmailVerificationRepository verifications, AccountRepository accounts,
                                    EmailRequestBudgetStore budget, AccountSettings settings,
                                    PlatformTransactionManager manager) {
        this.verifications = verifications;
        this.accounts = accounts;
        this.budget = budget;
        this.settings = settings;
        this.transaction = new TransactionTemplate(manager);
    }

    public Requested request(String purpose, String rawEmail, EntryTokenService.Claims entry, Account account) {
        String email = EmailAddress.normalize(rawEmail);
        if (purpose == null || !PURPOSES.contains(purpose)) {
            throw new BusinessError("INPUT_INVALID", 422, "不支持的验证用途");
        }
        if (purpose.equals("email_change")) {
            return requestEmailChange(email, account);
        }
        if (entry == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "账户入口已失效");
        }
        return transaction.execute(status -> purpose.equals("registration")
                ? requestRegistration(email, entry)
                : requestPasswordReset(email, entry));
    }

    private Requested requestRegistration(String email, EntryTokenService.Claims entry) {
        Instant now = Instant.now();
        if (accounts.existsByEmail(email)) {
            throw new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用");
        }
        reserve("registration", email, now);
        invalidateOpenRounds("registration", email, now);
        Instant expiresAt = now.plusSeconds(settings.emailCodeTtlSeconds());
        EmailVerification record = newRecord("registration", email, null, entry.nonceDigest(), null, now,
                expiresAt, UUID.randomUUID());
        verifications.save(record);
        return requested(record, expiresAt);
    }

    private Requested requestPasswordReset(String email, EntryTokenService.Claims entry) {
        Instant now = Instant.now();
        Account found = accounts.findByEmail(email).orElse(null);
        Account locked = found == null ? null : accounts.lockById(found.id()).orElse(null);
        if (locked != null && !EmailAddress.same(locked.email(), email)) {
            locked = null;
        }
        reserve("password_reset", email, now);
        Instant expiresAt = now.plusSeconds(settings.emailCodeTtlSeconds());
        if (locked == null) {
            long id = verifications.nextVerificationId();
            return new Requested(List.of(new Item(id, "password_reset", expiresAt)),
                    settings.emailResendIntervalSeconds());
        }
        invalidateOpenRounds("password_reset", email, now);
        EmailVerification record = newRecord("password_reset", email, locked.id(), entry.nonceDigest(),
                locked.credentialVersion(), now, expiresAt, UUID.randomUUID());
        verifications.save(record);
        return requested(record, expiresAt);
    }

    private Requested requestEmailChange(String newEmail, Account account) {
        if (account == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效");
        }
        return transaction.execute(status -> {
            Instant now = Instant.now();
            Account locked = accounts.lockById(account.id())
                    .orElseThrow(() -> new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效"));
            if (EmailAddress.same(locked.email(), newEmail)) {
                throw new BusinessError("EMAIL_UNCHANGED", 409, "新邮箱与当前邮箱相同");
            }
            if (accounts.existsByEmail(newEmail)) {
                throw new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用");
            }
            reserve("email_change", newEmail, now);
            verifications.invalidateEmailChange(locked.id(), now);
            Instant expiresAt = now.plusSeconds(settings.emailCodeTtlSeconds());
            UUID group = UUID.randomUUID();
            EmailVerification oldRow = newRecord("email_change_old", locked.email(), locked.id(), null,
                    locked.credentialVersion(), now, expiresAt, group);
            EmailVerification newRow = newRecord("email_change_new", newEmail, locked.id(), null,
                    locked.credentialVersion(), now, expiresAt, group);
            verifications.save(oldRow);
            verifications.save(newRow);
            return new Requested(List.of(new Item(oldRow.id(), oldRow.purpose(), expiresAt),
                    new Item(newRow.id(), newRow.purpose(), expiresAt)), settings.emailResendIntervalSeconds());
        });
    }

    private void reserve(String purpose, String email, Instant now) {
        long retryAfterSeconds = budget.reserve(purpose, email, now, settings.emailResendIntervalSeconds());
        if (retryAfterSeconds > 0L) {
            throw new BusinessError("RATE_LIMITED", 429, "请求过于频繁，请稍后再试",
                    Map.of("retry_after_seconds", retryAfterSeconds));
        }
    }

    private void invalidateOpenRounds(String purpose, String email, Instant now) {
        if (verifications.findLatestByPurposeAndEmail(purpose, email).isPresent()) {
            verifications.invalidateActiveByPurposeAndEmail(purpose, email, now);
        }
    }

    private EmailVerification newRecord(String purpose, String email, Long accountId, byte[] entryDigest,
                                        Integer credentialVersion, Instant now, Instant expiresAt, UUID group) {
        return new EmailVerification(purpose, email, accountId, entryDigest, group, credentialVersion, now,
                expiresAt, code(settings.emailCodeLength()), settings.emailCodeLength(),
                settings.emailCodeMaxFailedAttempts(), RULE_VERSION, rules(), now);
    }

    private Requested requested(EmailVerification record, Instant expiresAt) {
        return new Requested(List.of(new Item(record.id(), record.purpose(), expiresAt)),
                settings.emailResendIntervalSeconds());
    }

    private Map<String, Object> rules() {
        return Map.of("max_attempts", 3, "retry_seconds", settings.emailResendIntervalSeconds());
    }

    private static String code(int length) {
        StringBuilder value = new StringBuilder(length);
        for (int index = 0; index < length; index++) {
            value.append(RANDOM.nextInt(10));
        }
        return value.toString();
    }

    public record Item(long verificationId, String purpose, Instant expiresAt) {
    }

    public record Requested(List<Item> requests, int retryAfterSeconds) {
    }
}
