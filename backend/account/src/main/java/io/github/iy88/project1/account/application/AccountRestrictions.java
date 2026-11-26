package io.github.iy88.project1.account.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Objects;
import java.util.Optional;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Account-owned restriction facts and their effective-state reads.
 *
 * <p>Callers own the write transaction and idempotency. This service only writes the account ban
 * row. The write executor acquires the target account's exclusive qualification lock.
 */
@Service
@Profile("infrastructure")
public class AccountRestrictions {
    private static final String COLUMNS =
            "ban_id, account_id, case_id, applied_at, released_at";

    private final JdbcClient jdbc;
    private final Clock clock;

    public AccountRestrictions(JdbcClient jdbc, ObjectProvider<Clock> clocks) {
        this.jdbc = jdbc;
        this.clock = clocks.getIfAvailable(Clock::systemUTC);
    }

    /**
     * Records one source restriction or returns the already effective row for the same source.
     * The returned {@code alreadyEffective} flag is true when no write happened.
     */
    public Ban apply(WriteTransaction transaction, long accountId, long caseId, String reason,
                     String basisRef, Instant now) {
        requirePositive(accountId, "账户标识无效");
        requirePositive(caseId, "事项标识无效");
        String checkedReason = requireText(reason, "INPUT_INVALID", "封禁理由不能为空");
        String checkedBasis = requireText(basisRef, "BASIS_REQUIRED", "封禁依据不能为空");
        Objects.requireNonNull(now);
        long actorId = actor(transaction);
        transaction.requireExclusiveAccount(accountId);

        if (!jdbc.sql("select exists (select 1 from account where account_id = ?)")
                .param(accountId).query(Boolean.class).single()) {
            throw new BusinessError("TARGET_INVALID", 422, "目标账户不存在");
        }
        Optional<Ban> existing = findUnreleased(accountId, caseId);
        if (existing.isPresent()) {
            return existing.get().withAlreadyEffective(true);
        }

        long banId = jdbc.sql("""
                insert into account_ban (account_id, case_id, applied_by, applied_at, reason, basis_ref)
                values (?, ?, ?, ?, ?, ?)
                returning ban_id
                """).param(accountId).param(caseId).param(actorId).param(timestamp(now))
                .param(checkedReason).param(checkedBasis)
                .query(Long.class).single();
        return new Ban(banId, accountId, caseId, now, null, false);
    }

    /**
     * Releases exactly one account ban. Releasing a row that is already inactive, or was applied
     * after the caller's time, is a named conflict and writes nothing.
     */
    public Ban release(WriteTransaction transaction, long accountId, long caseId, long banId,
                       String reason, String basisRef, Instant now) {
        requirePositive(accountId, "账户标识无效");
        requirePositive(caseId, "事项标识无效");
        requirePositive(banId, "限制记录标识无效");
        String checkedReason = requireText(reason, "INPUT_INVALID", "解除理由不能为空");
        String checkedBasis = requireText(basisRef, "BASIS_REQUIRED", "解除依据不能为空");
        Objects.requireNonNull(now);
        long actorId = actor(transaction);
        transaction.requireExclusiveAccount(accountId);

        Ban found = find(banId)
                .orElseThrow(() -> new BusinessError("RESTRICTION_NOT_ACTIVE", 409, "限制记录不在生效状态"));
        if (found.accountId() != accountId || found.caseId() != caseId) {
            throw new BusinessError("OWNERSHIP_MISMATCH", 403, "限制记录不属于该账户或来源");
        }
        if (!found.active() || found.appliedAt().isAfter(now)) {
            throw new BusinessError("RESTRICTION_NOT_ACTIVE", 409, "限制记录不在生效状态");
        }

        int updated = jdbc.sql("""
                update account_ban
                set released_at = ?, released_by = ?, release_reason = ?, release_basis_ref = ?
                where ban_id = ? and released_at is null
                """).param(timestamp(now)).param(actorId).param(checkedReason)
                .param(checkedBasis).param(banId).update();
        if (updated != 1) {
            throw new BusinessError("RESTRICTION_NOT_ACTIVE", 409, "限制记录不在生效状态");
        }
        return new Ban(banId, accountId, caseId, found.appliedAt(), now, false);
    }

    /** Reads one restriction row by its identifier without changing state. */
    public Optional<Ban> find(long banId) {
        return jdbc.sql("select " + COLUMNS + " from account_ban where ban_id = ?")
                .param(banId)
                .query(AccountRestrictions::ban)
                .optional();
    }

    /** Resolves the effective record for one account and case source at the given time. */
    public Optional<Ban> findActive(long accountId, long caseId, Instant asOf) {
        Objects.requireNonNull(asOf);
        return jdbc.sql("select " + COLUMNS + """
                 from account_ban
                where account_id = ? and case_id = ?
                  and applied_at <= ? and (released_at is null or released_at > ?)
                order by ban_id desc
                limit 1
                """).param(accountId).param(caseId).param(timestamp(asOf)).param(timestamp(asOf))
                .query(AccountRestrictions::ban).optional();
    }

    public boolean isRestricted(long accountId, Instant asOf) {
        Objects.requireNonNull(asOf);
        return jdbc.sql("""
                select exists (
                    select 1 from account_ban
                    where account_id = ? and applied_at <= ?
                      and (released_at is null or released_at > ?)
                )
                """).param(accountId).param(timestamp(asOf)).param(timestamp(asOf))
                .query(Boolean.class).single();
    }

    public boolean isRestricted(long accountId) {
        return isRestricted(accountId, clock.instant());
    }

    /** Counts each effectively restricted account once at the given time. */
    public long countRestricted(OffsetDateTime asOf) {
        Objects.requireNonNull(asOf);
        return jdbc.sql("""
                select count(distinct account_id)
                from account_ban
                where applied_at <= ? and (released_at is null or released_at > ?)
                """).param(asOf).param(asOf).query(Long.class).single();
    }

    private Optional<Ban> findUnreleased(long accountId, long caseId) {
        return jdbc.sql("select " + COLUMNS + """
                 from account_ban
                where account_id = ? and case_id = ? and released_at is null
                order by ban_id desc
                limit 1
                """).param(accountId).param(caseId)
                .query(AccountRestrictions::ban).optional();
    }

    private static long actor(WriteTransaction transaction) {
        ExecutionContext context = transaction.context();
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要账户执行者");
        }
        return Long.parseLong(context.actorId());
    }

    private static void requirePositive(long value, String message) {
        if (value <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, message);
        }
    }

    private static String requireText(String value, String code, String message) {
        if (value == null || value.isBlank()) {
            throw new BusinessError(code, 422, message);
        }
        return value;
    }

    private static OffsetDateTime timestamp(Instant instant) {
        return OffsetDateTime.ofInstant(instant, ZoneOffset.UTC);
    }

    private static Ban ban(ResultSet row, int index) throws SQLException {
        OffsetDateTime releasedAt = row.getObject("released_at", OffsetDateTime.class);
        return new Ban(row.getLong("ban_id"), row.getLong("account_id"), row.getLong("case_id"),
                row.getObject("applied_at", OffsetDateTime.class).toInstant(),
                releasedAt == null ? null : releasedAt.toInstant(), false);
    }

    /**
     * One account restriction row. {@code alreadyEffective} is true only on an idempotent apply;
     * callers use {@link #active()} for the current state and {@link #id()} as the case result ref.
     */
    public record Ban(long id, long accountId, long caseId, Instant appliedAt, Instant releasedAt,
                      boolean alreadyEffective) {
        public boolean active() {
            return releasedAt == null;
        }

        private Ban withAlreadyEffective(boolean value) {
            return new Ban(id, accountId, caseId, appliedAt, releasedAt, value);
        }
    }
}
