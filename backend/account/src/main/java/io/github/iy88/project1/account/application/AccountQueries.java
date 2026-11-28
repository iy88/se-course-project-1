package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.persistence.AccountRepository;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/**
 * Read-only account projection used by cross-module callers. Restriction facts and their effective
 * state stay owned by {@link AccountRestrictions}; this projection only delegates the qualification
 * read.
 */
@Service
@Profile("infrastructure")
public class AccountQueries {
    private final AccountRepository accounts;
    private final AccountAvatarService avatars;
    private final AccountRestrictions restrictions;

    public AccountQueries(AccountRepository accounts, AccountAvatarService avatars,
                          AccountRestrictions restrictions) {
        this.accounts = accounts;
        this.avatars = avatars;
        this.restrictions = restrictions;
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
                foundAccounts.stream().map(entry -> entry.id()).toList());
        var found = new LinkedHashMap<Long, Profile>();
        for (var account : foundAccounts) {
            found.put(account.id(), new Profile(account.id(), account.displayName(),
                    avatarUrls.get(account.id())));
        }
        return found;
    }

    public boolean writeRestricted(long accountId) {
        return restrictions.isRestricted(accountId);
    }

    public record Profile(long accountId, String displayName, String avatarUrl) {
        public Profile(long accountId, String displayName) {
            this(accountId, displayName, null);
        }
    }
}
