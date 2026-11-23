package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.conversation.application.AccountDirectory;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Projects the account read model required by conversations. Restrictions stay with enforcement
 * (#81); the account projection reports none until that adapter is available.
 */
final class ConversationAccountDirectory implements AccountDirectory {
    private final AccountQueries accounts;

    ConversationAccountDirectory(AccountQueries accounts) {
        this.accounts = accounts;
    }

    @Override
    public Optional<Profile> profile(long accountId) {
        return accounts.profile(accountId)
                .map(profile -> new Profile(profile.accountId(), profile.displayName()));
    }

    @Override
    public boolean writeRestricted(long accountId) {
        return accounts.writeRestricted(accountId);
    }

    @Override
    public Map<Long, Profile> profiles(Set<Long> accountIds) {
        var profiles = new LinkedHashMap<Long, Profile>();
        accounts.profiles(accountIds).forEach((accountId, profile) ->
                profiles.put(accountId, new Profile(profile.accountId(), profile.displayName())));
        return profiles;
    }
}
