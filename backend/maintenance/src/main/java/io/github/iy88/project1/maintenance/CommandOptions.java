package io.github.iy88.project1.maintenance;

/** Applies command-specific option acceptance and defaults. */
final class CommandOptions {

    private static final String SEED_TAG_PATTERN = "[A-Za-z0-9._-]{1,64}";

    private CommandOptions() {
    }

    static MaintenanceCli.Options resolve(String command, ParsedOptions parsed) {
        return switch (command) {
            case "db init" -> Database.init(parsed);
            case "db migrate" -> Database.migrate(parsed);
            case "db validate" -> Database.validate(parsed);
            case "db backup" -> Database.backup(parsed);
            case "db reset" -> Database.reset(parsed);
            case "oss reset" -> Oss.reset(parsed);
            case "account create-manager" -> Account.createManager(parsed);
            case "seed load" -> Seed.load(parsed);
            case "seed demo" -> Seed.demo(parsed);
            default -> null;
        };
    }

    private static MaintenanceCli.Options defaultOptions(ParsedOptions parsed, String command) {
        return options(parsed, command, "demo", 100, 10000, 1L);
    }

    private static MaintenanceCli.Options options(ParsedOptions parsed, String command, String tag,
                                                  int users, int products, long seed) {
        return new MaintenanceCli.Options(parsed.envFile(), command, parsed.confirmation(),
                parsed.adminUser(), parsed.backupFile(), parsed.email(), parsed.displayName(),
                parsed.manifest(), tag, users, products, seed, parsed.prepareReset(), parsed.prefix());
    }

    private static final class Database {

        private Database() {
        }

        static MaintenanceCli.Options init(ParsedOptions parsed) {
            if (parsed.adminUser() == null || parsed.confirmation() != null
                    || parsed.backupFile() != null || parsed.email() != null
                    || parsed.displayName() != null || parsed.hasSeedOptions()
                    || parsed.prefix() != null) {
                return null;
            }
            return defaultOptions(parsed, "db init");
        }

        static MaintenanceCli.Options migrate(ParsedOptions parsed) {
            if (!onlyEnvironment(parsed)) {
                return null;
            }
            return defaultOptions(parsed, "db migrate");
        }

        static MaintenanceCli.Options validate(ParsedOptions parsed) {
            if (!onlyEnvironment(parsed)) {
                return null;
            }
            return defaultOptions(parsed, "db validate");
        }

        static MaintenanceCli.Options backup(ParsedOptions parsed) {
            if (parsed.backupFile() == null || parsed.adminUser() != null
                    || parsed.confirmation() != null || parsed.email() != null
                    || parsed.displayName() != null || parsed.hasSeedOptions()
                    || parsed.prefix() != null) {
                return null;
            }
            return defaultOptions(parsed, "db backup");
        }

        static MaintenanceCli.Options reset(ParsedOptions parsed) {
            if ((parsed.adminUser() != null && parsed.confirmation() == null)
                    || parsed.backupFile() != null || parsed.email() != null
                    || parsed.displayName() != null || parsed.hasSeedOptions()
                    || parsed.prefix() != null) {
                return null;
            }
            return defaultOptions(parsed, "db reset");
        }

        private static boolean onlyEnvironment(ParsedOptions parsed) {
            return parsed.confirmation() == null && parsed.adminUser() == null
                    && parsed.backupFile() == null && parsed.email() == null
                    && parsed.displayName() == null && !parsed.hasSeedOptions()
                    && parsed.prefix() == null;
        }
    }

    private static final class Oss {

        private Oss() {
        }

        static MaintenanceCli.Options reset(ParsedOptions parsed) {
            if (parsed.adminUser() != null || parsed.backupFile() != null
                    || parsed.email() != null || parsed.displayName() != null
                    || parsed.hasSeedOptions()) {
                return null;
            }
            return defaultOptions(parsed, "oss reset");
        }
    }

    private static final class Account {

        private Account() {
        }

        static MaintenanceCli.Options createManager(ParsedOptions parsed) {
            if (parsed.adminUser() != null || parsed.confirmation() != null
                    || parsed.backupFile() != null || parsed.email() == null
                    || parsed.displayName() == null || parsed.hasSeedOptions()
                    || parsed.prefix() != null) {
                return null;
            }
            return defaultOptions(parsed, "account create-manager");
        }
    }

    private static final class Seed {

        private Seed() {
        }

        static MaintenanceCli.Options load(ParsedOptions parsed) {
            if (!onlySeedOptions(parsed) || !validTag(parsed, "seed load")) {
                return null;
            }
            return seedOptions(parsed, "seed load");
        }

        static MaintenanceCli.Options demo(ParsedOptions parsed) {
            if (!onlySeedOptions(parsed) || !validTag(parsed, "seed demo")) {
                return null;
            }
            if (parsed.users() != null || parsed.products() != null) {
                // Demo scale is fixed by the catalog; accepting knobs would imply a different catalog.
                return null;
            }
            return seedOptions(parsed, "seed demo");
        }

        private static boolean onlySeedOptions(ParsedOptions parsed) {
            return parsed.adminUser() == null && parsed.confirmation() == null
                    && parsed.backupFile() == null && parsed.email() == null
                    && parsed.displayName() == null && parsed.prefix() == null;
        }

        private static boolean validTag(ParsedOptions parsed, String command) {
            return seedTag(parsed, command).matches(SEED_TAG_PATTERN);
        }

        private static MaintenanceCli.Options seedOptions(ParsedOptions parsed, String command) {
            return options(parsed, command, seedTag(parsed, command),
                    parsed.users() == null ? 100 : parsed.users(),
                    parsed.products() == null ? 10000 : parsed.products(),
                    parsed.seed() == null ? 1L : parsed.seed());
        }

        private static String seedTag(ParsedOptions parsed, String command) {
            return parsed.tag() == null ? (command.equals("seed load") ? "load" : "demo") : parsed.tag();
        }
    }
}
