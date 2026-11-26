package io.github.iy88.project1.api.product;

import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.product.application.CommentAccountAccess;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/**
 * Resolves comment author display names from the account module. Account restrictions are owned by
 * enforcement (#81); until that adapter is wired this projection reports no restriction, matching
 * the shared account read projection.
 */
@Component
@Profile("infrastructure")
class AccountCommentAccess implements CommentAccountAccess {
    private final AccountQueries accounts;

    AccountCommentAccess(AccountQueries accounts) {
        this.accounts = accounts;
    }

    @Override
    public Map<Long, Profile> profiles(Set<Long> accountIds) {
        if (accountIds.isEmpty()) {
            return Map.of();
        }
        var profiles = new LinkedHashMap<Long, Profile>();
        accounts.profiles(accountIds).forEach((accountId, profile) ->
                profiles.put(accountId, new Profile(profile.displayName(), profile.avatarUrl())));
        return profiles;
    }

    @Override
    public boolean writeRestricted(long accountId) {
        return false;
    }
}
