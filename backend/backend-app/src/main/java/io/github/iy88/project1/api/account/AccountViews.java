package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.SessionGuard;
import java.time.format.DateTimeFormatter;
import java.util.List;

final class AccountViews {
    private AccountViews() {
    }

    static IdentityView identity(Account account, SessionGuard guard) {
        return identity(account, guard, null);
    }

    static IdentityView identity(Account account, SessionGuard guard, String avatarUrl) {
        return new IdentityView(
                account(account, avatarUrl),
                new SessionView(guard.id().toString(), iso(guard.issuedAt()), iso(guard.absoluteExpiresAt())));
    }

    static IdentityView identity(io.github.iy88.project1.account.application.SessionService.Issued issued) {
        return identity(issued, null);
    }

    static IdentityView identity(io.github.iy88.project1.account.application.SessionService.Issued issued,
                                 String avatarUrl) {
        return new IdentityView(
                account(issued.account(), avatarUrl),
                new SessionView(issued.sessionId().toString(), iso(issued.issuedAt()),
                        iso(issued.absoluteExpiresAt())));
    }

    static AccountView account(Account account) {
        return account(account, null);
    }

    static AccountView account(Account account, String avatarUrl) {
        return new AccountView(Long.toString(account.id()), account.email(), account.displayName(),
                List.of(account.role()), avatarUrl);
    }

    private static String iso(java.time.Instant instant) {
        return DateTimeFormatter.ISO_INSTANT.format(instant);
    }

    record AccountView(String accountId, String email, String displayName, List<String> roles, String avatarUrl) {
    }

    record SessionView(String sessionId, String issuedAt, String absoluteExpiresAt) {
    }

    record IdentityView(AccountView account, SessionView session) {
    }
}
