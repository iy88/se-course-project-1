package io.github.iy88.project1.maintenance;

import io.github.iy88.project1.account.AccountInputRules;
import io.github.iy88.project1.account.application.EmailAddress;
import io.github.iy88.project1.account.application.PasswordHasher;
import java.sql.SQLException;
import java.time.Instant;
import java.util.UUID;

/** Account creation shared by seed load and seed demo: same validation, hashing, role and audit path. */
final class SeedAccounts {
    private final SeedDatabase database;
    private final SeedContext context;
    private final AccountInputRules inputs;
    private final String passwordHash;

    SeedAccounts(SeedDatabase database, SeedContext context) {
        this.database = database;
        this.context = context;
        inputs = new AccountInputRules(context.config().integerOrDefault("PASSWORD_MIN_LENGTH", 12),
                context.config().integerOrDefault("PASSWORD_MAX_LENGTH", 256),
                context.config().integerOrDefault("DISPLAY_NAME_MAX_LENGTH", 64));
        var password = context.password();
        inputs.requirePassword(password);
        passwordHash = new PasswordHasher().hash(password);
    }

    long create(String rawEmail, String displayName, String role, Instant createdAt) throws SQLException {
        String email = EmailAddress.normalize(rawEmail);
        String name = inputs.displayName(displayName);
        if ("manager".equals(role)) {
            return PostgresMaintenance.createManager(database.connection(), email, name, passwordHash,
                    context.configVersion());
        }
        if (!"user".equals(role)) {
            throw new IllegalArgumentException("Unsupported seed account role");
        }
        long id = database.insert("""
                insert into account (email, display_name, password_hash, credential_version, role, created_at)
                values (?, ?, ?, 1, ?, ?)
                returning account_id
                """, email, name, passwordHash, role, createdAt);
        UUID operationId = UUID.randomUUID();
        database.update("""
                insert into audit_record (request_id, operation_id, actor_kind, actor_id, action, target_type,
                                          target_id, facts, config_version)
                values (?, ?, 'system', 'maintenance:seed', 'account.seeded', 'account', ?, ?::jsonb, ?)
                """, operationId, operationId, id,
                "{\"mode\":" + SeedSupport.jsonString(context.mode()) + "}", context.configVersion());
        return id;
    }

}
