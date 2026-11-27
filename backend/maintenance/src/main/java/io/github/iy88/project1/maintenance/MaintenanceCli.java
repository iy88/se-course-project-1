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
                   java -jar maintenance.jar oss reset --env-file PATH [--confirm TOKEN] [--prefix PREFIX]
                   java -jar maintenance.jar account create-manager --env-file PATH --email EMAIL --display-name NAME
                   java -jar maintenance.jar seed load --env-file PATH [--manifest PATH] [--tag TAG]
                       [--users N] [--products N] [--seed N] --prepare-reset
                   java -jar maintenance.jar seed demo --env-file PATH [--manifest PATH] [--tag TAG]
                       [--seed N] --prepare-reset
            --env-file is required. Reset without --confirm previews the configured targets.
            Reads the owner and application logins from the same .env file.
            PostgreSQL administrator passwords are prompted for db init and legacy db reset.
            The manager's login password is prompted twice for account create-manager.
            Database reset uses the configured owner; --admin-user is only for legacy databases not owned by it.
            Stop all writers before executing reset.
            seed requires an explicit clean reset acknowledgement (--prepare-reset), an empty
            configured database and no objects below OSS_PREFIX; it never deletes data itself.
            oss reset without --prefix keeps the whole-bucket behavior. Use --prefix OSS_PREFIX
            for a shared bucket; the prefix is nonempty and segment-bounded.
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
        if (Arrays.asList(args).contains("--help")) {
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
                    String prefix = options.prefix();
                    if (confirmed(options, environment,
                            prefix == null ? oss.scope() : oss.prefixScope(prefix))) {
                        long removed = prefix == null ? oss.reset() : oss.resetPrefix(prefix);
                        System.out.println("OSS reset: complete (" + removed + " objects removed"
                                + (prefix == null ? ")" : " under " + OssMaintenance.normalizePrefix(prefix) + "/)"));
                    }
                }
                case "account create-manager" -> createManager(config, options);
                case "seed load", "seed demo" -> SeedRunner.run(config, options);
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
                   String email, String displayName, Path manifest, String tag, int users, int products,
                   long seed, boolean prepareReset, String prefix) {
        static Options parse(String[] args) {
            if (args.length < 3) {
                return null;
            }
            String command = args[0] + " " + args[1];
            ParseState state = new ParseState();
            for (int index = 2; index < args.length;) {
                String argument = args[index];
                if ("--prepare-reset".equals(argument) || "--reset".equals(argument)) {
                    if (state.prepareReset) {
                        return null;
                    }
                    state.prepareReset = true;
                    index++;
                    continue;
                }
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
                        if (state.envFile != null) return null;
                        try { state.envFile = Path.of(value); } catch (InvalidPathException ignored) { return null; }
                    }
                    case "--confirm" -> {
                        if (state.confirmation != null) return null;
                        state.confirmation = value;
                    }
                    case "--admin-user" -> {
                        if (state.adminUser != null) return null;
                        state.adminUser = value;
                    }
                    case "--backup-file" -> {
                        if (state.backupFile != null) return null;
                        try { state.backupFile = Path.of(value); } catch (InvalidPathException ignored) { return null; }
                    }
                    case "--email" -> {
                        if (state.email != null) return null;
                        state.email = value;
                    }
                    case "--display-name" -> {
                        if (state.displayName != null) return null;
                        state.displayName = value;
                    }
                    case "--manifest" -> {
                        if (state.manifest != null) return null;
                        try { state.manifest = Path.of(value); } catch (InvalidPathException ignored) { return null; }
                    }
                    case "--tag" -> {
                        if (state.tag != null) return null;
                        state.tag = value;
                    }
                    case "--users" -> {
                        if (state.users != null) return null;
                        state.users = integer(value);
                        if (state.users == null) return null;
                    }
                    case "--products" -> {
                        if (state.products != null) return null;
                        state.products = integer(value);
                        if (state.products == null) return null;
                    }
                    case "--seed" -> {
                        if (state.seed != null) return null;
                        try { state.seed = Long.parseLong(value); } catch (NumberFormatException invalid) { return null; }
                        if (state.seed < 0) return null;
                    }
                    case "--prefix" -> {
                        if (state.prefix != null) return null;
                        try {
                            if (!OssMaintenance.normalizePrefix(value).equals(value)) return null;
                        } catch (IllegalArgumentException invalid) {
                            return null;
                        }
                        state.prefix = value;
                    }
                    default -> {
                        return null;
                    }
                }
            }
            if (state.envFile == null) {
                return null;
            }
            boolean seedOptions = state.manifest != null || state.tag != null || state.users != null
                    || state.products != null || state.seed != null || state.prepareReset;
            boolean common = state.confirmation == null && state.adminUser == null && state.backupFile == null
                    && state.email == null && state.displayName == null && !seedOptions && state.prefix == null;
            boolean valid = switch (command) {
                case "db init" -> state.adminUser != null && state.confirmation == null
                        && state.backupFile == null && state.email == null && state.displayName == null
                        && !seedOptions && state.prefix == null;
                case "db migrate", "db validate" -> common;
                case "db backup" -> state.backupFile != null && state.adminUser == null && state.confirmation == null
                        && state.email == null && state.displayName == null && !seedOptions && state.prefix == null;
                case "db reset" -> (state.adminUser == null || state.confirmation != null)
                        && state.backupFile == null && state.email == null && state.displayName == null
                        && !seedOptions && state.prefix == null;
                case "oss reset" -> state.adminUser == null && state.backupFile == null && state.email == null
                        && state.displayName == null && !seedOptions;
                case "account create-manager" -> state.adminUser == null && state.confirmation == null
                        && state.backupFile == null && state.email != null && state.displayName != null
                        && !seedOptions && state.prefix == null;
                case "seed load", "seed demo" -> state.adminUser == null && state.confirmation == null
                        && state.backupFile == null && state.email == null && state.displayName == null
                        && state.prefix == null;
                default -> false;
            };
            if (!valid) {
                return null;
            }
            String tag = state.tag == null ? (command.equals("seed load") ? "load" : "demo") : state.tag;
            if (!tag.matches("[A-Za-z0-9._-]{1,64}")) {
                return null;
            }
            int users = state.users == null ? 100 : state.users;
            int products = state.products == null ? 10000 : state.products;
            long seed = state.seed == null ? 1L : state.seed;
            if (command.equals("seed demo") && (state.users != null || state.products != null)) {
                // Demo scale is fixed by the catalog; accepting knobs would imply a different catalog.
                return null;
            }
            return new Options(state.envFile, command, state.confirmation, state.adminUser, state.backupFile,
                    state.email, state.displayName, state.manifest, tag, users, products, seed,
                    state.prepareReset, state.prefix);
        }

        private static Integer integer(String value) {
            try {
                int parsed = Integer.parseInt(value);
                return parsed > 0 ? parsed : null;
            } catch (NumberFormatException invalid) {
                return null;
            }
        }

        private static final class ParseState {
            Path envFile;
            String confirmation;
            String adminUser;
            Path backupFile;
            String email;
            String displayName;
            Path manifest;
            String tag;
            Integer users;
            Integer products;
            Long seed;
            boolean prepareReset;
            String prefix;
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
