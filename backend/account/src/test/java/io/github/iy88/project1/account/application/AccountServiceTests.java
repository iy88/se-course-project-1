package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.account.persistence.EmailVerification;
import io.github.iy88.project1.account.persistence.EmailVerificationRepository;
import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.Arrays;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

/**
 * Account lifecycle rules that do not need HTTP cookies or a live mail delivery worker.
 *
 * <p>These cases exercise the service boundary directly: registration consumes the email
 * verification row, credential changes advance the credential version used by sessions, and
 * rejected inputs do not create or mutate accounts. Real PostgreSQL rollback and SMTP delivery are
 * covered separately by the account integration suites.
 */
class AccountServiceTests {
    private static final Instant NOW = Instant.now().minusSeconds(30);
    private static final String PASSWORD = "CorrectHorseBattery1";
    private static final byte[] ENTRY_DIGEST = digest(7);

    private final AccountRepository accounts = mock(AccountRepository.class);
    private final EmailVerificationRepository verifications = mock(EmailVerificationRepository.class);
    private final SessionService sessions = mock(SessionService.class);
    private final AccountAvatarService avatars = mock(AccountAvatarService.class);
    private final AccountSettings settings = new AccountSettings(12, 256, 64, 2_592_000, 604_800, 60,
            6, 600, 5, 60, 1_800, "01234567890123456789012345678901", "v1");
    private final PasswordHasher hasher = new PasswordHasher();
    private AccountService service;
    private long nextVerificationId;

    @BeforeEach
    void setUp() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        service = new AccountService(accounts, verifications, hasher, sessions, avatars, settings, manager);
        nextVerificationId = 55L;
        when(verifications.save(any(EmailVerification.class)))
                .thenAnswer(call -> call.getArgument(0));
        when(accounts.save(any(Account.class))).thenAnswer(call -> {
            Account account = call.getArgument(0);
            if (ReflectionTestUtils.getField(account, "id") == null) {
                ReflectionTestUtils.setField(account, "id", 77L);
            }
            return account;
        });
    }

    @Test
    void successfulRegistrationCreatesOneAccountAndConsumesTheVerification() {
        EmailVerification verification = registrationRound("New.User@Example.com", "123456", NOW.plusSeconds(3_600));
        when(verifications.lockById(verification.id())).thenReturn(Optional.of(verification));

        Account created = service.register("New.User@Example.com", " New User ", PASSWORD,
                verification.id(), "123456", entry());

        assertThat(created.id()).isEqualTo(77L);
        assertThat(created.email()).isEqualTo("New.User@Example.com");
        assertThat(created.displayName()).isEqualTo("New User");
        assertThat(hasher.matches(PASSWORD, created.passwordHash())).isTrue();
        assertThat(verification.consumed()).isTrue();
        assertThat(verification.code()).isNull();
        verify(accounts).save(any(Account.class));
    }

    @Test
    void reusingAConsumedVerificationRejectsTheSecondRegistration() {
        EmailVerification verification = registrationRound("new@example.com", "123456", NOW.plusSeconds(3_600));
        when(verifications.lockById(verification.id())).thenReturn(Optional.of(verification));

        service.register("new@example.com", "New User", PASSWORD, verification.id(), "123456", entry());
        BusinessError failure = catchThrowableOfType(
                () -> service.register("new@example.com", "New User", PASSWORD, verification.id(), "123456",
                        entry()),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("VERIFICATION_NOT_USABLE");
        assertThat(failure.status()).isEqualTo(422);
        verify(accounts).save(any(Account.class));
    }

    @Test
    void duplicateEmailConstraintIsReportedAsEmailInUse() {
        EmailVerification verification = registrationRound("taken@example.com", "123456", NOW.plusSeconds(3_600));
        when(verifications.lockById(verification.id())).thenReturn(Optional.of(verification));
        when(accounts.save(any(Account.class)))
                .thenThrow(new DataIntegrityViolationException("account email unique"));

        BusinessError failure = catchThrowableOfType(
                () -> service.register("taken@example.com", "Taken User", PASSWORD, verification.id(), "123456",
                        entry()),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("EMAIL_IN_USE");
        assertThat(failure.status()).isEqualTo(409);
    }

    @Test
    void aWrongRegistrationCodeRecordsOneFailureAndCreatesNoAccount() {
        EmailVerification verification = registrationRound("new@example.com", "123456", NOW.plusSeconds(3_600));
        when(verifications.lockById(verification.id())).thenReturn(Optional.of(verification));

        BusinessError failure = catchThrowableOfType(
                () -> service.register("new@example.com", "New User", PASSWORD, verification.id(), "999999",
                        entry()),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("VERIFICATION_CODE_INVALID");
        assertThat(verification.failedAttempts()).isEqualTo(1);
        verify(accounts, never()).save(any(Account.class));
        verify(verifications).save(verification);
    }

    @Test
    void anExpiredRegistrationCodeIsNotUsableAndCreatesNoAccount() {
        EmailVerification verification = registrationRound("new@example.com", "123456", NOW.minusSeconds(1));
        when(verifications.lockById(verification.id())).thenReturn(Optional.of(verification));

        BusinessError failure = catchThrowableOfType(
                () -> service.register("new@example.com", "New User", PASSWORD, verification.id(), "123456",
                        entry()),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("VERIFICATION_NOT_USABLE");
        verify(accounts, never()).save(any(Account.class));
    }

    @Test
    void loginRejectsAWrongPasswordWithoutIssuingASession() {
        Account account = account("user@example.com", 7L, PASSWORD);
        when(accounts.findByEmail("user@example.com")).thenReturn(Optional.of(account));

        BusinessError failure = catchThrowableOfType(
                () -> service.login("user@example.com", "WrongPassword123"), BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("CREDENTIALS_INVALID");
        assertThat(failure.status()).isEqualTo(401);
        verifyNoInteractions(sessions);
    }

    @Test
    void loginWithTheCurrentPasswordIssuesANewSession() {
        Account account = account("user@example.com", 7L, PASSWORD);
        when(accounts.findByEmail("user@example.com")).thenReturn(Optional.of(account));
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        UUID sessionId = UUID.randomUUID();
        SessionService.Prepared prepared = new SessionService.Prepared(sessionId, "token", "csrf", account, NOW,
                NOW.plusSeconds(60), digest(9));
        SessionService.Issued issued = new SessionService.Issued(sessionId, "token", "csrf", account, NOW,
                NOW.plusSeconds(60));
        when(sessions.prepare(account)).thenReturn(prepared);
        when(sessions.complete(prepared)).thenReturn(issued);

        SessionService.Issued result = service.login("user@example.com", PASSWORD);

        assertThat(result).isSameAs(issued);
        verify(sessions).prepare(account);
        verify(sessions).complete(prepared);
    }

    @Test
    void changingPasswordRejectsAWrongCurrentPasswordWithoutAdvancingTheVersion() {
        Account account = account("user@example.com", 7L, PASSWORD);

        BusinessError failure = catchThrowableOfType(
                () -> service.changePassword(account, "WrongPassword123", "AnotherPassword123"),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("CURRENT_PASSWORD_INVALID");
        assertThat(failure.status()).isEqualTo(422);
        assertThat(account.credentialVersion()).isEqualTo(1);
        verify(accounts, never()).save(any(Account.class));
    }

    @Test
    void changingPasswordAdvancesTheVersionAndAllowsOnlyTheNewPassword() {
        Account account = account("user@example.com", 7L, PASSWORD);
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        String newPassword = "AnotherPassword123";

        service.changePassword(account, PASSWORD, newPassword);

        assertThat(hasher.matches(PASSWORD, account.passwordHash())).isFalse();
        assertThat(hasher.matches(newPassword, account.passwordHash())).isTrue();
        assertThat(account.credentialVersion()).isEqualTo(2);
        verify(accounts).save(account);
    }

    @Test
    void resetPasswordConsumesTheRowAndKeepsTheSameAccountIdentity() {
        Account account = account("user@example.com", 7L, PASSWORD);
        EmailVerification verification = resetRound(account, "123456", NOW.plusSeconds(3_600));
        when(verifications.findAccountIdById(verification.id())).thenReturn(Optional.of(7L));
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        when(verifications.lockById(verification.id())).thenReturn(Optional.of(verification));
        String newPassword = "ResetPassword123";

        service.resetPassword(entry(), verification.id(), "123456", newPassword);

        assertThat(account.id()).isEqualTo(7L);
        assertThat(hasher.matches(newPassword, account.passwordHash())).isTrue();
        assertThat(account.credentialVersion()).isEqualTo(2);
        assertThat(verification.consumed()).isTrue();
        assertThat(verification.code()).isNull();
    }

    @Test
    void changingEmailConsumesBothRowsAndPreservesTheAccountIdentity() {
        Account account = account("old@example.com", 7L, PASSWORD);
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        EmailVerification oldRow = emailChangeRound("email_change_old", "old@example.com", "111111",
                UUID.randomUUID(), account.credentialVersion());
        EmailVerification newRow = emailChangeRound("email_change_new", "new@example.com", "222222",
                oldRow.groupId(), account.credentialVersion());
        when(verifications.lockById(oldRow.id())).thenReturn(Optional.of(oldRow));
        when(verifications.lockById(newRow.id())).thenReturn(Optional.of(newRow));

        Account changed = service.changeEmail(account, new AccountService.ChangeEmailCommand(
                "new@example.com", oldRow.id(), "111111", newRow.id(), "222222"));

        assertThat(changed.id()).isEqualTo(7L);
        assertThat(changed.email()).isEqualTo("new@example.com");
        assertThat(changed.credentialVersion()).isEqualTo(2);
        assertThat(oldRow.consumed()).isTrue();
        assertThat(newRow.consumed()).isTrue();
    }

    @Test
    void changingEmailRejectsRowsFromDifferentGroupsWithoutConsumingEither() {
        Account account = account("old@example.com", 7L, PASSWORD);
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        EmailVerification oldRow = emailChangeRound("email_change_old", "old@example.com", "111111",
                UUID.randomUUID(), account.credentialVersion());
        EmailVerification newRow = emailChangeRound("email_change_new", "new@example.com", "222222",
                UUID.randomUUID(), account.credentialVersion());
        when(verifications.lockById(oldRow.id())).thenReturn(Optional.of(oldRow));
        when(verifications.lockById(newRow.id())).thenReturn(Optional.of(newRow));

        BusinessError failure = catchThrowableOfType(
                () -> service.changeEmail(account, new AccountService.ChangeEmailCommand(
                        "new@example.com", oldRow.id(), "111111", newRow.id(), "222222")),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("VERIFICATION_CODE_INVALID");
        assertThat(oldRow.consumed()).isFalse();
        assertThat(newRow.consumed()).isFalse();
        verify(accounts, never()).save(any(Account.class));
    }

    @Test
    void changingToTheCurrentEmailIsRejectedBeforeWriting() {
        Account account = account("same@example.com", 7L, PASSWORD);

        BusinessError failure = catchThrowableOfType(
                () -> service.changeEmail(account, new AccountService.ChangeEmailCommand(
                        " SAME@example.com ", 1L, "111111", 2L, "222222")),
                BusinessError.class);

        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("EMAIL_UNCHANGED");
        assertThat(failure.status()).isEqualTo(409);
        verify(accounts, never()).save(any(Account.class));
    }

    private EmailVerification registrationRound(String email, String code, Instant expiresAt) {
        EmailVerification verification = new EmailVerification("registration", email, null, ENTRY_DIGEST,
                UUID.randomUUID(), null, NOW.minusSeconds(30), expiresAt, code, 6, 5, "s2-v1", Map.of(), NOW);
        ReflectionTestUtils.setField(verification, "id", nextVerificationId++);
        return verification;
    }

    private EmailVerification resetRound(Account account, String code, Instant expiresAt) {
        EmailVerification verification = new EmailVerification("password_reset", account.email(), account.id(),
                ENTRY_DIGEST, UUID.randomUUID(), account.credentialVersion(), NOW.minusSeconds(30), expiresAt,
                code, 6, 5, "s2-v1", Map.of(), NOW);
        ReflectionTestUtils.setField(verification, "id", nextVerificationId++);
        return verification;
    }

    private EmailVerification emailChangeRound(String purpose, String email, String code, UUID group,
                                               int credentialVersion) {
        EmailVerification verification = new EmailVerification(purpose, email, 7L, ENTRY_DIGEST, group,
                credentialVersion, NOW.minusSeconds(30), NOW.plusSeconds(3_600), code, 6, 5, "s2-v1", Map.of(),
                NOW);
        ReflectionTestUtils.setField(verification, "id", nextVerificationId++);
        return verification;
    }

    private static Account account(String email, long id, String password) {
        Account account = new Account(email, "User", new PasswordHasher().hash(password), NOW);
        ReflectionTestUtils.setField(account, "id", id);
        return account;
    }

    private static EntryTokenService.Claims entry() {
        return new EntryTokenService.Claims(ENTRY_DIGEST, digest(8), NOW.plusSeconds(1_800));
    }

    private static byte[] digest(int value) {
        byte[] bytes = new byte[32];
        Arrays.fill(bytes, (byte) value);
        return bytes;
    }
}
