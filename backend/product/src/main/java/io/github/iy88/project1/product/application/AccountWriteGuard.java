package io.github.iy88.project1.product.application;

import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.core.BusinessError;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

/**
 * BR-32 seller write qualification inside the caller's PostgreSQL transaction.
 *
 * <p>The shared advisory lock uses the same account key as the write executor, so an account ban
 * (exclusive lock, then product rows) cannot commit between this check and the product mutation.
 * Account security maintenance, case statements and appeals do not pass through this product
 * boundary.</p>
 */
@Component
@Profile("infrastructure")
public class AccountWriteGuard {
    private final JdbcClient jdbc;
    private final AccountQueries accounts;

    public AccountWriteGuard(JdbcClient jdbc, AccountQueries accounts) {
        this.jdbc = jdbc;
        this.accounts = accounts;
    }

    public void requireWritable(long accountId) {
        jdbc.sql("SELECT true FROM pg_advisory_xact_lock_shared(?)")
                .param(accountId).query(Boolean.class).single();
        if (accounts.writeRestricted(accountId)) {
            throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前受限，暂不可进行商品操作");
        }
    }
}
