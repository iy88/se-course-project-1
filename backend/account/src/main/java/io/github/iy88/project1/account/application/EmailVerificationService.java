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
import java.util.Optional;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class EmailVerificationService {
    private static final SecureRandom RANDOM = new SecureRandom();

    private final EmailVerificationRepository verifications;
    private final AccountRepository accounts;
    private final AccountSettings settings;
    private final AccountMailer mailer;
    private final TransactionTemplate transaction;

    public EmailVerificationService(EmailVerificationRepository verifications, AccountRepository accounts,
                                    AccountSettings settings, AccountMailer mailer,
                                    PlatformTransactionManager manager) {
        this.verifications = verifications;
        this.accounts = accounts;
        this.settings = settings;
        this.mailer = mailer;
        this.transaction = new TransactionTemplate(manager);
    }

    public Requested request(String purpose, String rawEmail, EntryTokenService.Claims entry, Account account) {
        String email = EmailAddress.normalize(rawEmail);
        if (purpose == null || !(purpose.equals("registration") || purpose.equals("password_reset")
                || purpose.equals("email_change"))) {
            throw new BusinessError("INPUT_INVALID", 422, "不支持的验证用途");
        }
        if (purpose.equals("email_change")) {
            return requestEmailChange(email, account);
        }
        if (entry == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "账户入口已失效");
        }
        Instant now = Instant.now();
        if (purpose.equals("registration") && accounts.existsByEmail(email)) {
            throw new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用");
        }
        Optional<Account> existing = purpose.equals("password_reset")
                ? accounts.findByEmail(email) : Optional.empty();
        if (purpose.equals("password_reset") && existing.isEmpty()) {
            return new Requested(List.of(), settings.emailResendIntervalSeconds());
        }
        String code = code(settings.emailCodeLength());
        Instant expiresAt = now.plusSeconds(settings.emailCodeTtlSeconds());
        EmailVerification record = new EmailVerification(purpose, email,
                existing.map(Account::id).orElse(null), entry.nonceDigest(), UUID.randomUUID(),
                existing.map(Account::credentialVersion).orElse(null), now, expiresAt, code,
                settings.emailCodeLength(), settings.emailCodeMaxFailedAttempts(), "s2-v1",
                rules(), now.plusSeconds(settings.emailResendIntervalSeconds()));
        transaction.executeWithoutResult(status -> verifications.save(record));
        send(email, code);
        markSent(record.id());
        return new Requested(List.of(new Item(record.id(), purpose, expiresAt)),
                settings.emailResendIntervalSeconds());
    }

    private Requested requestEmailChange(String newEmail, Account account) {
        if (account == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效");
        }
        if (EmailAddress.same(account.email(), newEmail)) {
            throw new BusinessError("EMAIL_UNCHANGED", 409, "新邮箱与当前邮箱相同");
        }
        if (accounts.existsByEmail(newEmail)) {
            throw new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用");
        }
        Instant now = Instant.now();
        Instant expiresAt = now.plusSeconds(settings.emailCodeTtlSeconds());
        UUID group = UUID.randomUUID();
        String oldCode = code(settings.emailCodeLength());
        String newCode = code(settings.emailCodeLength());
        EmailVerification oldRow = new EmailVerification("email_change_old", account.email(), account.id(), null,
                group, account.credentialVersion(), now, expiresAt, oldCode, settings.emailCodeLength(),
                settings.emailCodeMaxFailedAttempts(), "s2-v1", rules(),
                now.plusSeconds(settings.emailResendIntervalSeconds()));
        EmailVerification newRow = new EmailVerification("email_change_new", newEmail, account.id(), null,
                group, account.credentialVersion(), now, expiresAt, newCode, settings.emailCodeLength(),
                settings.emailCodeMaxFailedAttempts(), "s2-v1", rules(),
                now.plusSeconds(settings.emailResendIntervalSeconds()));
        transaction.executeWithoutResult(status -> {
            verifications.invalidateEmailChange(account.id(), now);
            verifications.save(oldRow);
            verifications.save(newRow);
        });
        send(account.email(), oldCode);
        send(newEmail, newCode);
        markSent(oldRow.id());
        markSent(newRow.id());
        return new Requested(List.of(new Item(oldRow.id(), "email_change_old", expiresAt),
                new Item(newRow.id(), "email_change_new", expiresAt)), settings.emailResendIntervalSeconds());
    }

    private Map<String, Object> rules() {
        return Map.of("max_attempts", 3, "retry_seconds", settings.emailResendIntervalSeconds());
    }

    private void send(String recipient, String code) {
        try {
            mailer.sendCode(recipient, code, settings.emailCodeTtlSeconds());
        } catch (RuntimeException failure) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "验证码发送失败，请稍后重试");
        }
    }

    private void markSent(long verificationId) {
        transaction.executeWithoutResult(status -> verifications.findById(verificationId).ifPresent(saved -> {
            saved.markSent(Instant.now());
            verifications.save(saved);
        }));
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
