package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/** Account-owned trade qualification, participant profiles and Session revalidation. */
@Service
@Profile("infrastructure")
public class AccountTradeService {
    private final AccountRepository accounts;
    private final AccountAvatarService avatars;
    private final SessionService sessions;

    public AccountTradeService(AccountRepository accounts, AccountAvatarService avatars,
                               SessionService sessions) {
        this.accounts = accounts;
        this.avatars = avatars;
        this.sessions = sessions;
    }

    public Qualification qualification(long accountId) {
        // Account restriction records are owned by the enforcement work (#81); until that schema is
        // committed an account has no persisted write restriction.
        return new Qualification(accounts.findById(accountId).isPresent(), false);
    }

    public Map<Long, Profile> profiles(Set<Long> accountIds) {
        if (accountIds.isEmpty()) {
            return Map.of();
        }
        List<Account> found = accounts.findByIdIn(accountIds);
        Map<Long, String> urls = avatars.currentUrls(found.stream().map(Account::id).toList());
        Map<Long, Profile> profiles = new LinkedHashMap<>();
        for (Account account : found) {
            profiles.put(account.id(), new Profile(account.id(), account.displayName(), urls.get(account.id())));
        }
        return Map.copyOf(profiles);
    }

    /** Rechecks the caller's Session under the write's account lock and re-validates its credential. */
    public void requireCurrentSession(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "登录状态已失效");
        }
        sessions.requireCurrent(Long.parseLong(context.actorId()), context.sessionId(),
                context.credentialVersion(), true);
    }

    public record Qualification(boolean exists, boolean writeRestricted) {
    }

    public record Profile(long accountId, String displayName, String avatarUrl) {
    }
}
