package io.github.iy88.project1.account.application;

import io.github.iy88.project1.core.BusinessError;
import java.time.OffsetDateTime;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class AccountManagementReadModel {
    private final JdbcClient jdbc;
    private final AccountRestrictions restrictions;

    public AccountManagementReadModel(JdbcClient jdbc, AccountRestrictions restrictions) {
        this.jdbc = jdbc;
        this.restrictions = restrictions;
    }

    public Counts counts(long managerId, OffsetDateTime asOf) {
        boolean manager = jdbc.sql("select exists(select 1 from account where account_id = ? and role = 'manager')")
                .param(managerId).query(Boolean.class).single();
        if (!manager) {
            throw new BusinessError("MANAGEMENT_NOT_ALLOWED", 403, "无管理权限");
        }
        long total = jdbc.sql("select count(*) from account").query(Long.class).single();
        return new Counts(total, restrictions.countRestricted(asOf));
    }

    public record Counts(long total, long banned) {}
}
