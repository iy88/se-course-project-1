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

    public AccountManagementReadModel(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Counts counts(long managerId, OffsetDateTime asOf) {
        boolean manager = jdbc.sql("select exists(select 1 from account where account_id = ? and role = 'manager')")
                .param(managerId).query(Boolean.class).single();
        if (!manager) {
            throw new BusinessError("MANAGEMENT_NOT_ALLOWED", 403, "无管理权限");
        }
        long total = jdbc.sql("select count(*) from account").query(Long.class).single();
        // The S3 schema has no ban facts. Once the account restriction migration adds these facts,
        // multiple simultaneous sources still count as one banned account.
        boolean hasBanFacts = jdbc.sql("select to_regclass('public.account_ban') is not null")
                .query(Boolean.class).single();
        long banned = hasBanFacts ? jdbc.sql("""
                select count(distinct account_id) from public.account_ban
                where applied_at <= :as_of and (released_at is null or released_at > :as_of)
                """).param("as_of", asOf).query(Long.class).single() : 0;
        return new Counts(total, banned);
    }

    public record Counts(long total, long banned) {}
}
