package io.github.iy88.project1.maintenance;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.Set;
import org.flywaydb.core.Flyway;
import org.postgresql.util.PasswordUtil;

final class PostgresMaintenance {

    private final MaintenanceConfig.PostgresUrl target;
    private final String appUser;
    private final String appPassword;
    private final String owner;
    private final String ownerPassword;

    PostgresMaintenance(MaintenanceConfig config) {
        target = config.postgresUrl("DATABASE_URL");
        appUser = config.matching("DATABASE_USERNAME", "[A-Za-z_][A-Za-z0-9_]{0,62}");
        appPassword = config.required("DATABASE_PASSWORD");
        owner = config.matching("DATABASE_OWNER_USERNAME", "[A-Za-z_][A-Za-z0-9_]{0,62}");
        ownerPassword = config.required("DATABASE_OWNER_PASSWORD");
        if (owner.equals(appUser)) {
            throw new IllegalArgumentException("DATABASE_OWNER_USERNAME must differ from DATABASE_USERNAME");
        }
        if (Set.of("postgres", "template0", "template1").contains(target.database())) {
            throw new IllegalArgumentException("PostgreSQL requires a dedicated application database");
        }
    }

    String scope() {
        return "PostgreSQL " + target.target() + " (owner " + owner + ", app " + appUser + ")";
    }

    void provision(boolean reset, String adminUser, char[] adminPassword) throws SQLException {
        if (appUser.equals(adminUser) || owner.equals(adminUser)) {
            throw new IllegalArgumentException("PostgreSQL administrator, owner and application login must be distinct");
        }
        try (Connection connection = connect(target.adminUrl(), "postgres", adminUser, new String(adminPassword))) {
            if (!"locked".equals(lookup(connection,
                    "SELECT CASE WHEN pg_try_advisory_lock(hashtext(?)::bigint) THEN 'locked' END", target.database()))) {
                throw new IllegalStateException("Another PostgreSQL maintenance operation holds the database lock");
            }
            String currentOwner = databaseOwner(connection);
            boolean previousSingleRole = appUser.equals(currentOwner);
            if (currentOwner != null && !owner.equals(currentOwner) && !(reset && previousSingleRole)) {
                throw new IllegalStateException(previousSingleRole
                        ? "The application owns the existing database. Use a confirmed reset to rebuild it with separate roles."
                        : "The configured owner does not own the existing database");
            }
            createRoleIfMissing(connection, owner, ownerPassword);
            createRoleIfMissing(connection, appUser, appPassword);
            ensureOwnerCanCreateDatabase(connection, owner);
            validateAppRole(connection);

            if (currentOwner != null && reset) {
                // Authenticate both roles before removing the database. PostgreSQL refuses DROP while clients are connected.
                verifyAppCredentials();
                try (var checked = previousSingleRole
                        ? connect(target.adminUrl(), "postgres", owner, ownerPassword)
                        : connect(target.jdbcUrl(), target.database(), owner, ownerPassword)) {
                    if (!checked.isValid(5)) {
                        throw new IllegalStateException("PostgreSQL owner connection validation failed");
                    }
                }
                execute(connection, "DROP DATABASE " + identifier(target.database()));
            }
            if (currentOwner == null || reset) {
                execute(connection, "CREATE DATABASE " + identifier(target.database())
                        + " OWNER " + identifier(owner));
            }
            migrate();
        }
    }

    void resetAsOwner() throws SQLException {
        try (Connection connection = connect(target.adminUrl(), "postgres", owner, ownerPassword)) {
            if (!"locked".equals(lookup(connection,
                    "SELECT CASE WHEN pg_try_advisory_lock(hashtext(?)::bigint) THEN 'locked' END", target.database()))) {
                throw new IllegalStateException("Another PostgreSQL maintenance operation holds the database lock");
            }
            String currentOwner = databaseOwner(connection);
            if (currentOwner == null) {
                throw new IllegalStateException("The target database does not exist. Run db init with an administrator");
            }
            if (!owner.equals(currentOwner)) {
                throw new IllegalStateException("The configured owner does not own the existing database. "
                        + "Use db reset with --admin-user for a legacy database");
            }
            validateOwnerCanReset(connection);
            verifyAppCredentials();
            try (var checked = connect(target.jdbcUrl(), target.database(), owner, ownerPassword)) {
                if (!checked.isValid(5)) {
                    throw new IllegalStateException("PostgreSQL owner connection validation failed");
                }
            }
            execute(connection, "DROP DATABASE " + identifier(target.database()));
            execute(connection, "CREATE DATABASE " + identifier(target.database())
                    + " OWNER " + identifier(owner));
            migrate();
        }
    }

    void migrate() throws SQLException {
        try (Connection connection = connect(target.jdbcUrl(), target.database(), owner, ownerPassword)) {
            if (!owner.equals(databaseOwner(connection))) {
                throw new IllegalStateException("The configured owner does not own the existing database");
            }
            validateAppRole(connection);
            restrictConnectionAndSchema(connection);
            Flyway.configure()
                    .dataSource(target.jdbcUrl(), owner, ownerPassword)
                    .defaultSchema("public")
                    .locations("classpath:db/migration")
                    .load()
                    .migrate();
            grantApplicationAccess(connection);
        }
        verifyAppCredentials();
    }

    private void validateAppRole(Connection connection) throws SQLException {
        String role = lookup(connection, """
                SELECT rolname FROM pg_roles
                WHERE rolname = ? AND rolcanlogin
                  AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
                  AND NOT EXISTS (SELECT FROM pg_auth_members WHERE member = pg_roles.oid)
                """, appUser);
        if (role == null) {
            throw new IllegalStateException("DATABASE_USERNAME must be a dedicated login without elevated privileges or role memberships");
        }
    }

    private void validateOwnerCanReset(Connection connection) throws SQLException {
        String role = lookup(connection, """
                SELECT rolname FROM pg_roles
                WHERE rolname = ? AND rolcanlogin AND rolcreatedb
                """, owner);
        if (role == null) {
            throw new IllegalStateException("DATABASE_OWNER_USERNAME must have CREATEDB. "
                    + "Run db init once with an administrator to update the role");
        }
    }

    private String databaseOwner(Connection connection) throws SQLException {
        return lookup(connection, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = ?", target.database());
    }

    private static void createRoleIfMissing(Connection connection, String user, String secret) throws SQLException {
        if (lookup(connection, "SELECT rolname FROM pg_roles WHERE rolname = ?", user) == null) {
            char[] password = secret.toCharArray();
            try {
                String verifier = PasswordUtil.encodeScramSha256(password);
                execute(connection, "CREATE ROLE " + identifier(user)
                        + " LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '" + verifier + "'");
            } finally {
                Arrays.fill(password, '\0');
            }
        }
    }

    private static void ensureOwnerCanCreateDatabase(Connection connection, String owner) throws SQLException {
        execute(connection, "ALTER ROLE " + identifier(owner) + " CREATEDB");
    }

    private void restrictConnectionAndSchema(Connection connection) throws SQLException {
        String database = identifier(target.database());
        String app = identifier(appUser);
        connection.setAutoCommit(false);
        execute(connection, "REVOKE ALL ON DATABASE " + database + " FROM PUBLIC, " + app);
        execute(connection, "GRANT CONNECT ON DATABASE " + database + " TO " + app);
        execute(connection, "REVOKE ALL ON SCHEMA public FROM PUBLIC, " + app);
        execute(connection, "GRANT USAGE ON SCHEMA public TO " + app);
        connection.commit();
        connection.setAutoCommit(true);
    }

    private void grantApplicationAccess(Connection connection) throws SQLException {
        String app = identifier(appUser);
        connection.setAutoCommit(false);
        execute(connection, "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, " + app);
        execute(connection, "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO " + app);
        execute(connection, "REVOKE ALL ON TABLE public.flyway_schema_history FROM " + app);
        execute(connection, "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, " + app);
        execute(connection, "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO " + app);
        connection.commit();
    }

    private void verifyAppCredentials() throws SQLException {
        try (Connection checked = connect(target.jdbcUrl(), target.database(), appUser, appPassword)) {
            if (!checked.isValid(5)) {
                throw new IllegalStateException("PostgreSQL application connection validation failed");
            }
        }
    }

    private static Connection connect(String url, String database, String user, String password)
            throws SQLException {
        Connection connection = DriverManager.getConnection(url, user, password);
        try {
            if (!database.equals(connection.getCatalog()) || !user.equals(connection.getMetaData().getUserName())) {
                throw new IllegalStateException("PostgreSQL connection targets an unexpected database or login");
            }
            return connection;
        } catch (SQLException | RuntimeException failure) {
            connection.close();
            throw failure;
        }
    }

    private static String lookup(Connection connection, String sql, String value) throws SQLException {
        try (var statement = connection.prepareStatement(sql)) {
            statement.setString(1, value);
            try (var rows = statement.executeQuery()) {
                return rows.next() ? rows.getString(1) : null;
            }
        }
    }

    private static void execute(Connection connection, String sql) throws SQLException {
        try (var statement = connection.createStatement()) {
            statement.executeUpdate(sql);
        }
    }

    private static String identifier(String value) {
        return "\"" + value + "\"";
    }

}
