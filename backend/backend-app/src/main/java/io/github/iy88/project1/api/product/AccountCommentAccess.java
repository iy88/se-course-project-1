package io.github.iy88.project1.api.product;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.product.application.CommentAccountAccess;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
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
    private final AccountRepository accounts;

    AccountCommentAccess(AccountRepository accounts) {
        this.accounts = accounts;
    }

    @Override
    public Map<Long, String> displayNames(Set<Long> accountIds) {
        if (accountIds.isEmpty()) {
            return Map.of();
        }
        return accounts.findByIdIn(accountIds).stream()
                .collect(Collectors.toMap(Account::id, Account::displayName, (first, second) -> first));
    }

    @Override
    public boolean writeRestricted(long accountId) {
        return false;
    }
}
