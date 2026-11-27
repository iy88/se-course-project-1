package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class AccountQueriesTests {
    private static final long ACCOUNT_ID = 7L;

    private final AccountRepository accounts = mock(AccountRepository.class);
    private final AccountRestrictions restrictions = mock(AccountRestrictions.class);
    private final AccountAvatarService avatars = mock(AccountAvatarService.class);
    private final AccountQueries queries = new AccountQueries(accounts, avatars, restrictions);

    @Test
    void aRestrictedAccountStillExposesItsReadOnlyProfileProjection() {
        Account account = new Account("user@example.com", "Restricted User", "hash", Instant.now());
        ReflectionTestUtils.setField(account, "id", ACCOUNT_ID);
        when(accounts.findById(ACCOUNT_ID)).thenReturn(Optional.of(account));
        when(restrictions.isRestricted(ACCOUNT_ID)).thenReturn(true);

        var profile = queries.profile(ACCOUNT_ID);

        assertThat(profile).isPresent();
        assertThat(profile.orElseThrow().displayName()).isEqualTo("Restricted User");
        assertThat(queries.writeRestricted(ACCOUNT_ID)).isTrue();
    }
}
