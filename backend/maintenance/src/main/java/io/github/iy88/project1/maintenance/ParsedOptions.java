package io.github.iy88.project1.maintenance;

import java.nio.file.InvalidPathException;
import java.nio.file.Path;

/** Holds option values during scanning until a command group validates them. */
final class ParsedOptions {

    private Path envFile;
    private String confirmation;
    private String adminUser;
    private Path backupFile;
    private String email;
    private String displayName;
    private Path manifest;
    private String tag;
    private Integer users;
    private Integer products;
    private Long seed;
    private boolean prepareReset;
    private String prefix;

    boolean markPrepareReset() {
        if (prepareReset) {
            return false;
        }
        prepareReset = true;
        return true;
    }

    boolean read(String option, String value) {
        return switch (option) {
            case "--env-file", "--backup-file", "--manifest" -> readPath(option, value);
            case "--confirm", "--admin-user", "--email", "--display-name", "--tag" -> readText(option, value);
            case "--users", "--products", "--seed" -> readNumber(option, value);
            case "--prefix" -> readPrefix(value);
            default -> false;
        };
    }

    private boolean readPath(String option, String value) {
        switch (option) {
            case "--env-file" -> {
                if (envFile != null) {
                    return false;
                }
                try {
                    envFile = Path.of(value);
                } catch (InvalidPathException ignored) {
                    return false;
                }
            }
            case "--backup-file" -> {
                if (backupFile != null) {
                    return false;
                }
                try {
                    backupFile = Path.of(value);
                } catch (InvalidPathException ignored) {
                    return false;
                }
            }
            case "--manifest" -> {
                if (manifest != null) {
                    return false;
                }
                try {
                    manifest = Path.of(value);
                } catch (InvalidPathException ignored) {
                    return false;
                }
            }
            default -> {
                return false;
            }
        }
        return true;
    }

    private boolean readText(String option, String value) {
        switch (option) {
            case "--confirm" -> {
                if (confirmation != null) return false;
                confirmation = value;
            }
            case "--admin-user" -> {
                if (adminUser != null) return false;
                adminUser = value;
            }
            case "--email" -> {
                if (email != null) return false;
                email = value;
            }
            case "--display-name" -> {
                if (displayName != null) return false;
                displayName = value;
            }
            case "--tag" -> {
                if (tag != null) return false;
                tag = value;
            }
            default -> {
                return false;
            }
        }
        return true;
    }

    private boolean readNumber(String option, String value) {
        switch (option) {
            case "--users" -> {
                if (users != null) return false;
                users = positiveInteger(value);
                if (users == null) return false;
            }
            case "--products" -> {
                if (products != null) return false;
                products = positiveInteger(value);
                if (products == null) return false;
            }
            case "--seed" -> {
                if (seed != null) return false;
                try {
                    seed = Long.parseLong(value);
                } catch (NumberFormatException invalid) {
                    return false;
                }
                if (seed < 0) return false;
            }
            default -> {
                return false;
            }
        }
        return true;
    }

    private boolean readPrefix(String value) {
        if (prefix != null) {
            return false;
        }
        try {
            if (!OssMaintenance.normalizePrefix(value).equals(value)) {
                return false;
            }
        } catch (IllegalArgumentException invalid) {
            return false;
        }
        prefix = value;
        return true;
    }

    boolean hasSeedOptions() {
        return manifest != null || tag != null || users != null || products != null
                || seed != null || prepareReset;
    }

    Path envFile() { return envFile; }
    String confirmation() { return confirmation; }
    String adminUser() { return adminUser; }
    Path backupFile() { return backupFile; }
    String email() { return email; }
    String displayName() { return displayName; }
    Path manifest() { return manifest; }
    String tag() { return tag; }
    Integer users() { return users; }
    Integer products() { return products; }
    Long seed() { return seed; }
    boolean prepareReset() { return prepareReset; }
    String prefix() { return prefix; }

    private static Integer positiveInteger(String value) {
        try {
            int parsed = Integer.parseInt(value);
            return parsed > 0 ? parsed : null;
        } catch (NumberFormatException invalid) {
            return null;
        }
    }
}
