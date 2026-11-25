package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.account.application.AccountTradeService;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradePorts.AccountProfile;
import io.github.iy88.project1.trade.application.TradePorts.AccountQualification;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/** Account-owned implementation of the trade qualification and profile ports. */
final class TradeAccountsAdapter implements TradePorts.Accounts {
    private final AccountTradeService accounts;

    TradeAccountsAdapter(AccountTradeService accounts) {
        this.accounts = accounts;
    }

    @Override
    public void requireCurrentSession(ExecutionContext context) {
        accounts.requireCurrentSession(context);
    }

    @Override
    public AccountQualification qualification(long accountId) {
        var qualification = accounts.qualification(accountId);
        return new AccountQualification(accountId, qualification.exists(), qualification.writeRestricted());
    }

    @Override
    public Map<Long, AccountProfile> profiles(Set<Long> accountIds) {
        Map<Long, AccountProfile> profiles = new LinkedHashMap<>();
        accounts.profiles(accountIds).forEach((accountId, profile) -> profiles.put(accountId,
                new AccountProfile(accountId, profile.displayName(), profile.avatarUrl())));
        return Map.copyOf(profiles);
    }
}
