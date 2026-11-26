package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AccountTradeServiceTests {
    private final AccountRepository accounts = mock(AccountRepository.class);
    private final AccountAvatarService avatars = mock(AccountAvatarService.class);
    private final SessionService sessions = mock(SessionService.class);
    private final AccountTradeService service = new AccountTradeService(accounts, avatars, sessions);

    @Test
    void qualificationReportsOnlyPersistedAccounts() {
        when(accounts.findById(7)).thenReturn(Optional.of(mock(Account.class)));
        when(accounts.findById(8)).thenReturn(Optional.empty());

        assertThat(service.qualification(7)).isEqualTo(new AccountTradeService.Qualification(true, false));
        assertThat(service.qualification(8)).isEqualTo(new AccountTradeService.Qualification(false, false));
    }

    @Test
    void sessionRevalidationIsDelegatedWithTheAccountLock() {
        UUID sessionId = UUID.randomUUID();
        service.requireCurrentSession(new ExecutionContext(UUID.randomUUID(),
                ExecutionContext.ActorKind.ACCOUNT, "7", sessionId, null, 4L, "cfg"));

        verify(sessions).requireCurrent(7, sessionId, 4L, true);
    }

    @Test
    void nonAccountActorsCannotRevalidateASession() {
        assertThatThrownBy(() -> service.requireCurrentSession(new ExecutionContext(UUID.randomUUID(),
                ExecutionContext.ActorKind.SYSTEM, "job", null, null, null, "cfg")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("AUTHENTICATION_REQUIRED"));
    }

    @Test
    void profilesCarryTheCurrentAvatarWhenPresent() {
        Account withAvatar = account(1, "甲");
        Account withoutAvatar = account(2, "乙");
        when(accounts.findByIdIn(Set.of(1L, 2L))).thenReturn(List.of(withAvatar, withoutAvatar));
        when(avatars.currentUrls(List.of(1L, 2L))).thenReturn(Map.of(1L, "https://cdn/avatar"));

        var profiles = service.profiles(Set.of(1L, 2L));

        assertThat(profiles.get(1L)).isEqualTo(new AccountTradeService.Profile(1, "甲", "https://cdn/avatar"));
        assertThat(profiles.get(2L)).isEqualTo(new AccountTradeService.Profile(2, "乙", null));
    }

    private static Account account(long id, String displayName) {
        Account account = mock(Account.class);
        when(account.id()).thenReturn(id);
        when(account.displayName()).thenReturn(displayName);
        return account;
    }
}
