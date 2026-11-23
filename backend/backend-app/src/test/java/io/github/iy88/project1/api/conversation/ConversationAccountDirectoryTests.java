package io.github.iy88.project1.api.conversation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.conversation.application.AccountDirectory;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;

class ConversationAccountDirectoryTests {
    private final AccountQueries accounts = mock(AccountQueries.class);
    private final ConversationAccountDirectory directory = new ConversationAccountDirectory(accounts);

    @Test
    void mapsProfilesOntoTheConversationPort() {
        when(accounts.profile(7L)).thenReturn(Optional.of(new AccountQueries.Profile(7L, "张新悦")));
        when(accounts.profiles(Set.of(7L, 42L))).thenReturn(Map.of(
                7L, new AccountQueries.Profile(7L, "张新悦"),
                42L, new AccountQueries.Profile(42L, "李四")));

        assertThat(directory.profile(7L)).contains(new AccountDirectory.Profile(7L, "张新悦"));
        assertThat(directory.profiles(Set.of(7L, 42L))).containsEntry(42L,
                new AccountDirectory.Profile(42L, "李四"));
    }

    @Test
    void reportsNoRestrictionUntilEnforcementIsWired() {
        assertThat(directory.writeRestricted(7L)).isFalse();
    }
}
