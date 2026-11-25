package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/**
 * Read-only account projection used by cross-module callers. Account restrictions are owned by
 * enforcement (#81); until that adapter is wired this projection reports no restriction so the
 * conversation module does not depend on an undelivered table.
 */
@Service
@Profile("infrastructure")
public class AccountQueries {
    private final AccountRepository accounts;
    private final AccountAvatarService avatars;

    public AccountQueries(AccountRepository accounts, AccountAvatarService avatars) {
        this.accounts = accounts;
        this.avatars = avatars;
    }

    public Optional<Profile> profile(long accountId) {
        return accounts.findById(accountId)
                .map(account -> new Profile(account.id(), account.displayName(),
                        avatars.currentUrl(account.id())));
    }

    public Map<Long, Profile> profiles(Collection<Long> accountIds) {
        if (accountIds.isEmpty()) {
            return Map.of();
        }
        var foundAccounts = accounts.findByIdIn(accountIds);
        Map<Long, String> avatarUrls = avatars.currentUrls(
                foundAccounts.stream().map(Account::id).toList());
        var found = new LinkedHashMap<Long, Profile>();
        for (var account : foundAccounts) {
            found.put(account.id(), new Profile(account.id(), account.displayName(),
                    avatarUrls.get(account.id())));
        }
        return found;
    }

    public boolean writeRestricted(long accountId) {
        return false;
    }

    public record Profile(long accountId, String displayName, String avatarUrl) {
        public Profile(long accountId, String displayName) {
            this(accountId, displayName, null);
        }
    }
}
