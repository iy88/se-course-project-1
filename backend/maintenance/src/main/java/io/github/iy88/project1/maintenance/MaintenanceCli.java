package io.github.iy88.project1.maintenance;

import io.github.iy88.project1.account.AccountInputRules;
import io.github.iy88.project1.account.application.EmailAddress;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.core.BusinessError;
import io.lettuce.core.RedisException;
import java.io.IOException;
import java.nio.CharBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Arrays;
import java.util.HexFormat;
import org.flywaydb.core.api.FlywayException;

public final class MaintenanceCli {

    private static final String USAGE = """
            Usage: java -jar maintenance.jar db init --env-file PATH --admin-user USER
                   java -jar maintenance.jar db migrate --env-file PATH
                   java -jar maintenance.jar db backup --env-file PATH --backup-file PATH
                   java -jar maintenance.jar db validate --env-file PATH
                   java -jar maintenance.jar db reset --env-file PATH
                   java -jar maintenance.jar db reset --env-file PATH --confirm TOKEN [--admin-user USER]
                   java -jar maintenance.jar oss reset --env-file PATH [--confirm TOKEN]
                   java -jar maintenance.jar account create-manager --env-file PATH --email EMAIL --display-name NAME
            --env-file is required. Reset without --confirm previews the configured targets.
            Reads the owner and application logins from the same .env file.
            PostgreSQL administrator passwords are prompted for db init and legacy db reset.
            The manager's login password is prompted twice for account create-manager.
            Database reset uses the configured owner; --admin-user is only for legacy databases not owned by it.
            Stop all writers before executing reset.
            """;

    private MaintenanceCli() {
    }

    public static void main(String[] args) {
        int status = run(args);
        if (status != 0) {
            System.exit(status);
        }
    }

    private static int run(String[] args) {
        if (args.length == 1 && args[0].equals("--help")) {
            System.out.print(USAGE);
            return 0;
        }
        Options options = Options.parse(args);
        if (options == null) {
            System.err.print(USAGE);
            return 2;
        }

        try {
            var config = new MaintenanceConfig(options.envFile());
            String environment = config.matching("APP_ENV", "[A-Za-z0-9_-]+");
            System.out.println("Environment: " + environment);
            DriverManager.setLoginTimeout(5);
            switch (options.command()) {
                case "db init" -> {
                    var postgres = new PostgresMaintenance(config);
                    System.out.println(postgres.scope());
                    provision(postgres, options, null);
                    System.out.println("PostgreSQL initialization and migration: complete");
                }
                case "db migrate" -> {
                    var postgres = new PostgresMaintenance(config);
                    System.out.println(postgres.scope());
                    postgres.migrate();
                    System.out.println("PostgreSQL migration and application grants: complete");
                }
                case "db backup" -> new PostgresMaintenance(config).backup(options.backupFile());
                case "db validate" -> new PostgresMaintenance(config).validate();
                case "db reset" -> {
                    var postgres = new PostgresMaintenance(config);
                    var redis = new RedisMaintenance(config);
                    if (confirmed(options, environment, postgres.scope() + "\n" + redis.scope())) {
                        if (options.adminUser() == null) {
                            redis.resetAfter(postgres::resetAsOwner);
                        } else {
                            provision(postgres, options, redis);
                        }
                    }
                }
                case "oss reset" -> {
                    var oss = new OssMaintenance(config);
                    if (confirmed(options, environment, oss.scope())) {
                        long removed = oss.reset();
                        System.out.println("OSS reset: complete (" + removed + " objects removed)");
                    }
                }
                case "account create-manager" -> createManager(config, options);
                default -> throw new AssertionError(options.command());
            }
            return 0;
        } catch (SQLException failure) {
            String state = failure.getSQLState();
            if ("55006".equals(state)) {
                System.err.println("PostgreSQL database is in use (SQLSTATE 55006). Stop connected services and retry.");
            } else {
                System.err.println("PostgreSQL step failed (SQLSTATE " + state + ")");
            }
        } catch (RedisException failure) {
            System.err.println("Redis step failed (" + failure.getClass().getSimpleName() + ")");
        } catch (FlywayException failure) {
            System.err.println("Flyway migration failed (" + failure.getClass().getSimpleName() + ")");
        } catch (BusinessError failure) {
            System.err.println(failure.getMessage());
        } catch (IllegalArgumentException | IllegalStateException failure) {
            System.err.println(failure.getMessage());
        } catch (IOException failure) {
            System.err.println("Unable to read configuration or prepare the database backup");
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            System.err.println("PostgreSQL backup interrupted");
        }
        return 1;
    }

    private static void createManager(MaintenanceConfig config, Options options) throws SQLException {
        var postgres = new PostgresMaintenance(config);
        var inputs = new AccountInputRules(config.integerOrDefault("PASSWORD_MIN_LENGTH", 12),
                config.integerOrDefault("PASSWORD_MAX_LENGTH", 256),
                config.integerOrDefault("DISPLAY_NAME_MAX_LENGTH", 64));
        String email = EmailAddress.normalize(options.email());
        String name = inputs.displayName(options.displayName());
        String configVersion = config.valueOrDefault("CONFIG_VERSION", "s1-v1");
        System.out.println(postgres.scope());
        var console = System.console();
        if (console == null || !console.isTerminal()) {
            throw new IllegalStateException("A terminal is required to enter the manager password.");
        }

        char[] password = console.readPassword("Manager password: ");
        char[] confirmation = null;
        try {
            inputs.requirePassword(password == null ? null : CharBuffer.wrap(password));
            confirmation = console.readPassword("Confirm manager password: ");
            if (!Arrays.equals(password, confirmation)) {
                throw new IllegalArgumentException("Manager passwords do not match.");
            }
            String passwordHash = new PasswordHasher().hash(password);
            long id = postgres.createManager(email, name, passwordHash, configVersion);
            System.out.println("Manager account created (account ID " + id + ").");
        } finally {
            if (password != null) {
                Arrays.fill(password, '\0');
            }
            if (confirmation != null) {
                Arrays.fill(confirmation, '\0');
            }
        }
    }

    private static void provision(PostgresMaintenance postgres, Options options, RedisMaintenance redis)
            throws SQLException {
        withAdminPassword(admin -> {
            if (redis == null) {
                postgres.provision(false, options.adminUser(), admin);
            } else {
                redis.resetAfter(() -> postgres.provision(true, options.adminUser(), admin));
            }
        });
    }

    private static void withAdminPassword(DatabaseCommand command) throws SQLException {
        var console = System.console();
        if (console == null || !console.isTerminal()) {
            throw new IllegalStateException("A terminal is required to enter the PostgreSQL administrator password.");
        }
        char[] password = console.readPassword("PostgreSQL administrator password: ");
        try {
            if (password == null || password.length == 0) {
                throw new IllegalArgumentException("PostgreSQL administrator password is required.");
            }
            command.run(password);
        } finally {
            if (password != null) {
                Arrays.fill(password, '\0');
            }
        }
    }

    private static boolean confirmed(Options options, String environment, String scopes) {
        System.out.println(scopes);
        String token = token(options.command() + "\n" + environment + "\n" + scopes);
        if (options.confirmation() == null) {
            System.out.println("Preview only. Stop all writers, then rerun with --confirm " + token);
            return false;
        }
        if (!token.equals(options.confirmation())) {
            throw new IllegalArgumentException("Confirmation does not match these targets. Run the preview again.");
        }
        return true;
    }

    @FunctionalInterface
    private interface DatabaseCommand {
        void run(char[] password) throws SQLException;
    }

    record Options(Path envFile, String command, String confirmation, String adminUser, Path backupFile,
                   String email, String displayName) {
        static Options parse(String[] args) {
            if (args.length < 3 || args.length > 8) {
                return null;
            }
            String command = args[0] + " " + args[1];
            Path envFile = null;
            String confirmation = null;
            String admin = null;
            Path backupFile = null;
            String email = null;
            String displayName = null;
            for (int index = 2; index < args.length;) {
                String argument = args[index];
                String option;
                String value;
                int equals = argument.indexOf('=');
                if (argument.startsWith("--") && equals > 2) {
                    option = argument.substring(0, equals);
                    value = argument.substring(equals + 1);
                    index++;
                } else {
                    if (index + 1 >= args.length) {
                        return null;
                    }
                    option = argument;
                    value = args[index + 1];
                    index += 2;
                }
                if (value.isBlank() || value.startsWith("--")) {
                    return null;
                }
                switch (option) {
                    case "--env-file" -> {
                        if (envFile != null) {
                            return null;
                        }
                        try {
                            envFile = Path.of(value);
                        } catch (InvalidPathException ignored) {
                            return null;
                        }
                    }
                    case "--confirm" -> {
                        if (confirmation != null) {
                            return null;
                        }
                        confirmation = value;
                    }
                    case "--admin-user" -> {
                        if (admin != null) {
                            return null;
                        }
                        admin = value;
                    }
                    case "--backup-file" -> {
                        if (backupFile != null) {
                            return null;
                        }
                        try {
                            backupFile = Path.of(value);
                        } catch (InvalidPathException invalidPath) {
                            return null;
                        }
                    }
                    case "--email" -> {
                        if (email != null) {
                            return null;
                        }
                        email = value;
                    }
                    case "--display-name" -> {
                        if (displayName != null) {
                            return null;
                        }
                        displayName = value;
                    }
                    default -> {
                        return null;
                    }
                }
            }
            boolean createManager = command.equals("account create-manager");
            if (envFile == null || (backupFile != null && !command.equals("db backup"))
                    || (!createManager && (email != null || displayName != null))) {
                return null;
            }
            boolean valid = switch (command) {
                case "db init" -> admin != null && confirmation == null;
                case "db migrate", "db validate" -> admin == null && confirmation == null;
                case "db backup" -> admin == null && confirmation == null && backupFile != null;
                case "db reset" -> admin == null || confirmation != null;
                case "oss reset" -> admin == null;
                case "account create-manager" -> admin == null && confirmation == null
                        && email != null && displayName != null;
                default -> false;
            };
            return valid ? new Options(envFile, command, confirmation, admin, backupFile, email, displayName) : null;
        }
    }

    private static String token(String scope) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(scope.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash, 0, 8);
        } catch (NoSuchAlgorithmException failure) {
            throw new IllegalStateException("SHA-256 is unavailable");
        }
    }
}
