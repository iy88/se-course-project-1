package io.github.iy88.project1.maintenance;

import java.nio.file.Path;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Base64;

/** Validated, secret-aware context shared by both seed modes. No value here is printed. */
final class SeedContext {
    private static final DateTimeFormatter STAMP =
            DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssSSS'Z'").withZone(ZoneOffset.UTC);
    private static final SecureRandom RANDOM = new SecureRandom();

    private final MaintenanceConfig config;
    private final String mode;
    private final String tag;
    private final String runId;
    private final String shortRun;
    private final String password;
    private final long seed;
    private final int users;
    private final int products;
    private final Path manifestPath;
    private final String configVersion;
    private final String region;
    private final String endpoint;
    private final String bucket;
    private final String prefix;
    private final String redisNamespace;
    private final Clock clock;

    private SeedContext(MaintenanceConfig config, MaintenanceCli.Options options, String mode) {
        this.config = config;
        this.mode = mode;
        tag = options.tag();
        runId = mode + "-" + tag + "-" + STAMP.format(Instant.now());
        shortRun = SeedSupport.sha256Hex(runId).substring(0, 12);
        password = randomPassword();
        seed = options.seed();
        users = options.users();
        products = options.products();
        configVersion = config.valueOrDefault("CONFIG_VERSION", "s1-v1");
        region = config.matching("OSS_REGION", "[a-z0-9-]+");
        endpoint = config.required("OSS_ENDPOINT");
        bucket = config.matching("OSS_BUCKET", "[a-z0-9][a-z0-9-]{1,61}[a-z0-9]");
        prefix = OssMaintenance.normalizePrefix(config.required("OSS_PREFIX"));
        redisNamespace = config.matching("REDIS_NAMESPACE", "[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*");
        String defaultManifest = "var/" + mode + "/manifest-" + runId + ".json";
        manifestPath = options.manifest() == null ? Path.of(defaultManifest) : options.manifest();
        clock = Clock.systemUTC();
    }

    static SeedContext create(MaintenanceConfig config, MaintenanceCli.Options options, String mode) {
        return new SeedContext(config, options, mode);
    }

    MaintenanceConfig config() { return config; }
    String mode() { return mode; }
    String tag() { return tag; }
    String runId() { return runId; }
    String password() { return password; }
    long seed() { return seed; }
    int users() { return users; }
    int products() { return products; }
    Path manifestPath() { return manifestPath; }
    String configVersion() { return configVersion; }
    String region() { return region; }
    String endpoint() { return endpoint; }
    String bucket() { return bucket; }
    String prefix() { return prefix; }
    String redisNamespace() { return redisNamespace; }
    Clock clock() { return clock; }

    String loadEmail(int index) {
        return "seed-load-" + shortRun + "-u%03d@example.test".formatted(index);
    }

    String managerEmail() {
        return "seed-" + mode + "-" + shortRun + "-manager@example.test";
    }

    String demoEmail(String key) {
        return "demo-" + key + "@example.test";
    }

    private static String randomPassword() {
        byte[] bytes = new byte[24];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
