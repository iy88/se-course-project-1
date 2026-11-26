package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
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
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class EmailVerificationServiceTests {
    private static final Instant NOW = Instant.parse("2026-11-23T00:00:00Z");
    private static final String EMAIL = "user@example.com";

    private final EmailVerificationRepository verifications = mock(EmailVerificationRepository.class);
    private final AccountRepository accounts = mock(AccountRepository.class);
    private final EmailRequestBudgetStore budget = mock(EmailRequestBudgetStore.class);
    private final AccountSettings settings = new AccountSettings(12, 256, 64, 3600, 3600, 60,
            6, 600, 5, 60, 1800, "01234567890123456789012345678901", "v1");
    private final EntryTokenService.Claims entry = new EntryTokenService.Claims(
            digest(1), digest(2), Instant.now().plusSeconds(1800));
    private EmailVerificationService service;
    private long nextId;

    @BeforeEach
    void setUp() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        service = new EmailVerificationService(verifications, accounts, budget, settings, manager);
        nextId = 500L;
        when(verifications.save(any(EmailVerification.class))).thenAnswer(call -> {
            EmailVerification verification = call.getArgument(0);
            ReflectionTestUtils.setField(verification, "id", nextId++);
            return verification;
        });
    }

    @Test
    void unknownPasswordResetReturnsOneUnlinkableItemWithoutSavingVerification() {
        when(accounts.findByEmail("missing@example.com")).thenReturn(Optional.empty());
        when(budget.reserve(eq("password_reset"), eq("missing@example.com"), any(), eq(60))).thenReturn(0L);
        when(verifications.findLatestByPurposeAndEmail("password_reset", "missing@example.com"))
                .thenReturn(Optional.empty());
        when(verifications.nextVerificationId()).thenReturn(4242L);

        var result = service.request("password_reset", " missing@example.com ", entry, null);

        assertThat(result.retryAfterSeconds()).isEqualTo(60);
        assertThat(result.requests()).singleElement().satisfies(item -> {
            assertThat(item.verificationId()).isEqualTo(4242L);
            assertThat(item.purpose()).isEqualTo("password_reset");
            assertThat(item.expiresAt()).isAfter(Instant.now().plusSeconds(500));
        });
        verify(verifications, never()).save(any());
        verify(verifications, never()).invalidateActiveByPurposeAndEmail(anyString(), anyString(), any());
    }

    @Test
    void knownPasswordResetInvalidatesOlderRoundAndSavesOneItem() {
        Account account = account(EMAIL, 7L);
        when(accounts.findByEmail(EMAIL)).thenReturn(Optional.of(account));
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        when(budget.reserve(eq("password_reset"), eq(EMAIL), any(), eq(60))).thenReturn(0L);
        when(verifications.findLatestByPurposeAndEmail("password_reset", EMAIL))
                .thenReturn(Optional.of(round("password_reset", EMAIL, 7L, 1)));

        var result = service.request("password_reset", EMAIL, entry, null);

        assertThat(result.requests()).singleElement().satisfies(item -> {
            assertThat(item.verificationId()).isEqualTo(500L);
            assertThat(item.purpose()).isEqualTo("password_reset");
        });
        InOrder order = inOrder(accounts, budget, verifications);
        order.verify(accounts).lockById(7L);
        order.verify(budget).reserve(eq("password_reset"), eq(EMAIL), any(), eq(60));
        order.verify(verifications).findLatestByPurposeAndEmail("password_reset", EMAIL);
        order.verify(verifications).invalidateActiveByPurposeAndEmail(eq("password_reset"), eq(EMAIL), any());
        ArgumentCaptor<EmailVerification> saved = ArgumentCaptor.forClass(EmailVerification.class);
        order.verify(verifications).save(saved.capture());
        assertThat(saved.getValue().accountId()).isEqualTo(7L);
        assertThat(saved.getValue().credentialVersion()).isEqualTo(1);
        assertThat(saved.getValue().entryDigest()).isEqualTo(entry.nonceDigest());
        verify(verifications, never()).nextVerificationId();
    }

    @Test
    void knownAndUnknownPasswordResetShareTheSameRateLimitedShape() {
        when(accounts.findByEmail("missing@example.com")).thenReturn(Optional.empty());
        when(budget.reserve(eq("password_reset"), eq("missing@example.com"), any(), anyInt())).thenReturn(30L);

        BusinessError unknown = catchThrowableOfType(
                () -> service.request("password_reset", "missing@example.com", entry, null),
                BusinessError.class);

        Account account = account(EMAIL, 7L);
        when(accounts.findByEmail(EMAIL)).thenReturn(Optional.of(account));
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        when(budget.reserve(eq("password_reset"), eq(EMAIL), any(), anyInt())).thenReturn(30L);

        BusinessError known = catchThrowableOfType(
                () -> service.request("password_reset", EMAIL, entry, null), BusinessError.class);

        assertThat(unknown.code()).isEqualTo("RATE_LIMITED");
        assertThat(known.code()).isEqualTo(unknown.code());
        assertThat(unknown.status()).isEqualTo(429);
        assertThat(known.status()).isEqualTo(unknown.status());
        assertThat(unknown.details()).isEqualTo(Map.of("retry_after_seconds", 30L));
        assertThat(known.details()).isEqualTo(unknown.details());
        assertThat(known.getMessage()).isEqualTo(unknown.getMessage());
        assertThat(known.getMessage()).doesNotContain(EMAIL);
        verify(verifications, never()).save(any());
        verify(verifications, never()).invalidateActiveByPurposeAndEmail(anyString(), anyString(), any());
        verify(verifications, never()).nextVerificationId();
    }

    @Test
    void registrationInvalidatesOpenRoundsForTheSameAddressAcrossEntryChanges() {
        when(accounts.existsByEmail("new@example.com")).thenReturn(false);
        when(budget.reserve(eq("registration"), eq("new@example.com"), any(), eq(60))).thenReturn(0L);
        when(verifications.findLatestByPurposeAndEmail("registration", "new@example.com"))
                .thenReturn(Optional.of(round("registration", "new@example.com", null, null)));

        var result = service.request("registration", "new@example.com", entry, null);

        assertThat(result.requests()).singleElement()
                .satisfies(item -> assertThat(item.purpose()).isEqualTo("registration"));
        verify(verifications).invalidateActiveByPurposeAndEmail(eq("registration"), eq("new@example.com"), any());
        ArgumentCaptor<EmailVerification> saved = ArgumentCaptor.forClass(EmailVerification.class);
        verify(verifications).save(saved.capture());
        assertThat(saved.getValue().entryDigest()).isEqualTo(entry.nonceDigest());
        assertThat(saved.getValue().purpose()).isEqualTo("registration");
    }

    @Test
    void emailChangeUsesTheSharedBudgetAndInvalidatesTheExistingGroup() {
        Account account = account("old@example.com", 7L);
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        when(accounts.existsByEmail("new@example.com")).thenReturn(false);
        when(budget.reserve(eq("email_change"), eq("new@example.com"), any(), eq(60))).thenReturn(0L);

        var result = service.request("email_change", "new@example.com", null, account);

        assertThat(result.requests()).extracting(EmailVerificationService.Item::purpose)
                .containsExactly("email_change_old", "email_change_new");
        verify(budget).reserve(eq("email_change"), eq("account:7"), any(), eq(60));
        verify(budget).reserve(eq("email_change"), eq("new@example.com"), any(), eq(60));
        verify(verifications).invalidateEmailChange(eq(7L), any());
        ArgumentCaptor<EmailVerification> saved = ArgumentCaptor.forClass(EmailVerification.class);
        verify(verifications, org.mockito.Mockito.times(2)).save(saved.capture());
        assertThat(saved.getAllValues()).extracting(EmailVerification::purpose)
                .containsExactly("email_change_old", "email_change_new");
    }

    @Test
    void rateLimitedEmailChangeDoesNotInvalidateTheExistingGroupOrCreateRows() {
        Account account = account("old@example.com", 7L);
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        when(accounts.existsByEmail("new@example.com")).thenReturn(false);
        when(budget.reserve(eq("email_change"), eq("new@example.com"), any(), anyInt())).thenReturn(15L);

        BusinessError failure = catchThrowableOfType(
                () -> service.request("email_change", "new@example.com", null, account), BusinessError.class);

        assertThat(failure.code()).isEqualTo("RATE_LIMITED");
        assertThat(failure.status()).isEqualTo(429);
        assertThat(failure.details()).isEqualTo(Map.of("retry_after_seconds", 15L));
        verify(verifications, never()).invalidateEmailChange(anyLong(), any());
        verify(verifications, never()).save(any());
    }

    @Test
    void changingTheDestinationDoesNotBypassTheAccountBudget() {
        Account account = account("old@example.com", 7L);
        when(accounts.lockById(7L)).thenReturn(Optional.of(account));
        when(budget.reserve(eq("email_change"), eq("account:7"), any(), anyInt())).thenReturn(20L);

        BusinessError failure = catchThrowableOfType(
                () -> service.request("email_change", "different@example.com", null, account),
                BusinessError.class);

        assertThat(failure.code()).isEqualTo("RATE_LIMITED");
        verify(budget, never()).reserve(eq("email_change"), eq("different@example.com"), any(), anyInt());
        verify(verifications, never()).invalidateEmailChange(anyLong(), any());
        verify(verifications, never()).save(any());
    }

    @Test
    void registrationStillReturnsEmailInUseBeforeConsumingTheBudget() {
        when(accounts.existsByEmail(EMAIL)).thenReturn(true);

        BusinessError failure = catchThrowableOfType(
                () -> service.request("registration", EMAIL, entry, null), BusinessError.class);

        assertThat(failure.code()).isEqualTo("EMAIL_IN_USE");
        assertThat(failure.status()).isEqualTo(409);
        verify(budget, never()).reserve(anyString(), anyString(), any(), anyInt());
        verify(verifications, never()).save(any());
    }

    private static Account account(String email, long id) {
        Account account = new Account(email, "User", "hash", NOW);
        ReflectionTestUtils.setField(account, "id", id);
        return account;
    }

    private static EmailVerification round(String purpose, String email, Long accountId, Integer version) {
        EmailVerification verification = new EmailVerification(purpose, email, accountId, digest(9),
                UUID.randomUUID(), version, NOW, NOW.plusSeconds(600), "123456", 6, 5, "s2-v1",
                Map.of(), NOW);
        ReflectionTestUtils.setField(verification, "id", 99L);
        return verification;
    }

    private static byte[] digest(int value) {
        byte[] bytes = new byte[32];
        Arrays.fill(bytes, (byte) value);
        return bytes;
    }
}
