package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.core.BusinessError;
import java.time.OffsetDateTime;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class AccountManagementReadModel {
    private final AccountRepository accounts;
    private final AccountRestrictions restrictions;

    public AccountManagementReadModel(AccountRepository accounts, AccountRestrictions restrictions) {
        this.accounts = accounts;
        this.restrictions = restrictions;
    }

    public Counts counts(long managerId, OffsetDateTime asOf) {
        if (!accounts.existsByIdAndRole(managerId, "manager")) {
            throw new BusinessError("MANAGEMENT_NOT_ALLOWED", 403, "无管理权限");
        }
        return new Counts(accounts.count(), restrictions.countRestricted(asOf));
    }

    public record Counts(long total, long banned) {}
}
