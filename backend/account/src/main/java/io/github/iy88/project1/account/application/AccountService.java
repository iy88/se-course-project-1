package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.EmailVerification;
import io.github.iy88.project1.account.persistence.EmailVerificationRepository;
import io.github.iy88.project1.core.BusinessError;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
@Profile("infrastructure")
public class AccountService {
    private final AccountRepository accounts;
    private final EmailVerificationRepository verifications;
    private final PasswordHasher hasher;
    private final SessionService sessions;
    private final AccountAvatarService avatars;
    private final AccountSettings settings;
    private final TransactionTemplate transaction;

    public AccountService(AccountRepository accounts, EmailVerificationRepository verifications,
                          PasswordHasher hasher, SessionService sessions, AccountAvatarService avatars,
                          AccountSettings settings, PlatformTransactionManager manager) {
        this.accounts = accounts;
        this.verifications = verifications;
        this.hasher = hasher;
        this.sessions = sessions;
        this.avatars = avatars;
        this.settings = settings;
        this.transaction = new TransactionTemplate(manager);
    }

    public Account register(String rawEmail, String displayName, String password, long verificationId, String code,
                            EntryTokenService.Claims entry) {
        String email = EmailAddress.normalize(rawEmail);
        String name = name(displayName);
        password(password);
        if (entry == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "账户入口已失效");
        }
        String hash = hasher.hash(password);
        try {
            Object result = transaction.execute(status -> {
                Instant now = Instant.now();
                EmailVerification verification = verifications.lockById(verificationId)
                        .orElseThrow(() -> new BusinessError("VERIFICATION_CODE_INVALID", 422, "验证码无效"));
                if (!"registration".equals(verification.purpose())
                        || !EmailAddress.same(verification.email(), email)
                        || !MessageDigest.isEqual(verification.entryDigest(), entry.nonceDigest())) {
                    return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
                }
                if (!verification.usable(now)) {
                    return new Failure("VERIFICATION_NOT_USABLE", 422, "验证码已失效");
                }
                if (!verification.matches(code)) {
                    verification.recordFailure(now);
                    verifications.save(verification);
                    return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
                }
                verification.consume(now);
                verifications.save(verification);
                return accounts.save(new Account(email, name, hash, now));
            });
            if (result instanceof Failure failure) {
                throw new BusinessError(failure.code, failure.status, failure.message);
            }
            return (Account) result;
        } catch (DataIntegrityViolationException duplicate) {
            throw new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用");
        }
    }

    public SessionService.Issued login(String rawEmail, String password) {
        String email;
        try {
            email = EmailAddress.normalize(rawEmail);
        } catch (BusinessError invalid) {
            hasher.matchesDummy(password);
            throw new BusinessError("CREDENTIALS_INVALID", 401, "邮箱或密码错误");
        }
        Optional<Account> found = accounts.findByEmail(email);
        if (found.isEmpty()) {
            hasher.matchesDummy(password);
            throw new BusinessError("CREDENTIALS_INVALID", 401, "邮箱或密码错误");
        }
        if (!hasher.matches(password, found.get().passwordHash())) {
            throw new BusinessError("CREDENTIALS_INVALID", 401, "邮箱或密码错误");
        }
        Account current = transaction.execute(status -> accounts.lockById(found.get().id())
                .orElseThrow(() -> new BusinessError("CREDENTIALS_INVALID", 401, "邮箱或密码错误")));
        return sessions.issue(current);
    }

    public void changePassword(Account account, String currentPassword, String newPassword) {
        password(newPassword);
        if (!hasher.matches(currentPassword, account.passwordHash())) {
            throw new BusinessError("CURRENT_PASSWORD_INVALID", 422, "当前密码不正确");
        }
        String hash = hasher.hash(newPassword);
        transaction.executeWithoutResult(status -> {
            Account locked = accounts.lockById(account.id())
                    .orElseThrow(() -> new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效"));
            if (!hasher.matches(currentPassword, locked.passwordHash())) {
                throw new BusinessError("CURRENT_PASSWORD_INVALID", 422, "当前密码不正确");
            }
            locked.replacePassword(hash);
            accounts.save(locked);
        });
    }

    public void resetPassword(EntryTokenService.Claims entry, long verificationId, String code, String newPassword) {
        password(newPassword);
        String hash = hasher.hash(newPassword);
        Object result = transaction.execute(status -> {
            Instant now = Instant.now();
            EmailVerification verification = verifications.lockById(verificationId)
                    .orElseThrow(() -> new BusinessError("VERIFICATION_CODE_INVALID", 422, "验证码无效"));
            if (!"password_reset".equals(verification.purpose())
                    || verification.entryDigest() == null
                    || !MessageDigest.isEqual(verification.entryDigest(), entry.nonceDigest())
                    || verification.accountId() == null) {
                return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
            }
            if (!verification.usable(now)) {
                return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
            }
            Account account = accounts.lockById(verification.accountId())
                    .orElseThrow(() -> new BusinessError("VERIFICATION_CODE_INVALID", 422, "验证码无效"));
            if (verification.credentialVersion() == null
                    || account.credentialVersion() != verification.credentialVersion()) {
                return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
            }
            if (!verification.matches(code)) {
                verification.recordFailure(now);
                verifications.save(verification);
                return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
            }
            verification.consume(now);
            verifications.save(verification);
            account.replacePassword(hash);
            accounts.save(account);
            return Boolean.TRUE;
        });
        if (result instanceof Failure failure) {
            throw new BusinessError(failure.code, failure.status, failure.message);
        }
    }

    public Account changeEmail(Account account, ChangeEmailCommand command) {
        String newEmail = EmailAddress.normalize(command.newEmail());
        if (EmailAddress.same(account.email(), newEmail)) {
            throw new BusinessError("EMAIL_UNCHANGED", 409, "新邮箱与当前邮箱相同");
        }
        try {
            Object result = transaction.execute(status -> {
                Instant now = Instant.now();
                Account locked = accounts.lockById(account.id())
                        .orElseThrow(() -> new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效"));
                long firstId = Math.min(command.oldVerificationId(), command.newVerificationId());
                long secondId = Math.max(command.oldVerificationId(), command.newVerificationId());
                EmailVerification first = verifications.lockById(firstId)
                        .orElseThrow(() -> new BusinessError("VERIFICATION_CODE_INVALID", 422, "验证码无效"));
                EmailVerification second = verifications.lockById(secondId)
                        .orElseThrow(() -> new BusinessError("VERIFICATION_CODE_INVALID", 422, "验证码无效"));
                EmailVerification oldRow = command.oldVerificationId() == firstId ? first : second;
                EmailVerification newRow = command.oldVerificationId() == firstId ? second : first;
                if (!validEmailChange(oldRow, newRow, locked, newEmail)) {
                    return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
                }
                if (!oldRow.usable(now) || !newRow.usable(now)) {
                    return new Failure("VERIFICATION_NOT_USABLE", 422, "验证码已失效");
                }
                boolean oldMatches = oldRow.matches(command.oldCode());
                boolean newMatches = newRow.matches(command.newCode());
                if (!oldMatches || !newMatches) {
                    if (!oldMatches) {
                        oldRow.recordFailure(now);
                    }
                    if (!newMatches) {
                        newRow.recordFailure(now);
                    }
                    verifications.save(oldRow);
                    verifications.save(newRow);
                    return new Failure("VERIFICATION_CODE_INVALID", 422, "验证码无效");
                }
                oldRow.consume(now);
                newRow.consume(now);
                verifications.save(oldRow);
                verifications.save(newRow);
                locked.changeEmail(newEmail);
                return accounts.save(locked);
            });
            if (result instanceof Failure failure) {
                throw new BusinessError(failure.code, failure.status, failure.message);
            }
            return (Account) result;
        } catch (DataIntegrityViolationException duplicate) {
            throw new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用");
        }
    }

    private static boolean validEmailChange(EmailVerification oldRow, EmailVerification newRow, Account account,
                                            String newEmail) {
        return "email_change_old".equals(oldRow.purpose())
                && "email_change_new".equals(newRow.purpose())
                && oldRow.groupId() != null && oldRow.groupId().equals(newRow.groupId())
                && oldRow.accountId() != null && oldRow.accountId() == account.id()
                && newRow.accountId() != null && newRow.accountId() == account.id()
                && oldRow.credentialVersion() != null && newRow.credentialVersion() != null
                && oldRow.credentialVersion() == account.credentialVersion()
                && newRow.credentialVersion() == account.credentialVersion()
                && EmailAddress.same(oldRow.email(), account.email())
                && EmailAddress.same(newRow.email(), newEmail);
    }

    public Account updateProfile(Account account, String displayName, String avatarFileId) {
        if (displayName == null && avatarFileId == null) {
            throw new BusinessError("INPUT_INVALID", 422, "没有可更新的资料");
        }
        String name = displayName == null ? null : name(displayName);
        Long avatar = avatarFileId == null ? null : avatarId(avatarFileId);
        return transaction.execute(status -> {
            Account locked = accounts.lockById(account.id())
                    .orElseThrow(() -> new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效"));
            if (name != null) {
                locked.rename(name);
            }
            avatars.replace(locked.id(), avatar);
            return accounts.save(locked);
        });
    }

    private static Long avatarId(String value) {
        String text = value.trim();
        if (text.isEmpty() || "0".equals(text)) {
            return 0L;
        }
        try {
            long id = Long.parseLong(text);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new BusinessError("INPUT_INVALID", 422, "头像标识无效");
    }

    private String name(String value) {
        String name = value == null ? "" : value.trim();
        if (name.isEmpty() || name.codePointCount(0, name.length()) > settings.displayNameMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "显示名称无效");
        }
        return name;
    }

    private void password(String value) {
        int length = value == null ? 0 : value.codePointCount(0, value.length());
        if (length < settings.passwordMinLength() || length > settings.passwordMaxLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "密码长度不符合要求");
        }
    }

    public record ChangeEmailCommand(String newEmail, long oldVerificationId, String oldCode,
                                     long newVerificationId, String newCode) {
    }

    private record Failure(String code, int status, String message) {
    }
}
