package io.github.iy88.project1.account.application;

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

    public AccountQueries(AccountRepository accounts) {
        this.accounts = accounts;
    }

    public Optional<Profile> profile(long accountId) {
        return accounts.findById(accountId).map(AccountQueries::profile);
    }

    public Map<Long, Profile> profiles(Collection<Long> accountIds) {
        if (accountIds.isEmpty()) {
            return Map.of();
        }
        var found = new LinkedHashMap<Long, Profile>();
        for (var account : accounts.findByIdIn(accountIds)) {
            found.put(account.id(), profile(account));
        }
        return found;
    }

    public boolean writeRestricted(long accountId) {
        return false;
    }

    private static Profile profile(io.github.iy88.project1.account.persistence.Account account) {
        return new Profile(account.id(), account.displayName());
    }

    public record Profile(long accountId, String displayName) {
    }
}
