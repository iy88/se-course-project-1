package io.github.iy88.project1.maintenance;

import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.ScanArgs;
import io.lettuce.core.ScanCursor;
import io.lettuce.core.api.sync.RedisCommands;
import io.lettuce.core.codec.ByteArrayCodec;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.time.Duration;
import java.util.Arrays;

final class RedisMaintenance {

    private final RedisURI uri;
    private final String prefix;
    private final byte[] prefixBytes;

    RedisMaintenance(MaintenanceConfig config) {
        prefix = config.matching("REDIS_NAMESPACE", "[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*") + ":";
        prefixBytes = prefix.getBytes(StandardCharsets.UTF_8);
        String url = config.required("REDIS_URL");
        try {
            URI address = URI.create(url);
            if (!(url.startsWith("redis://") || url.startsWith("rediss://"))
                    || address.getHost() == null || address.getFragment() != null
                    || address.getPort() == 0 || address.getPort() > 65535) {
                throw new IllegalArgumentException();
            }
            uri = RedisURI.create(url);
            uri.setTimeout(Duration.ofSeconds(5));
        } catch (IllegalArgumentException ignored) {
            throw new IllegalArgumentException("Invalid configuration: REDIS_URL (expected one Redis server)");
        }
    }

    String scope() {
        return "Redis " + (uri.isSsl() ? "rediss" : "redis") + " " + uri.getHost() + ":" + uri.getPort()
                + " db=" + uri.getDatabase() + " keys=" + prefix + "*";
    }

    void resetAfter(SqlStep resetPostgres) throws SQLException {
        RedisClient client = RedisClient.create(uri);
        try (var connection = client.connect(ByteArrayCodec.INSTANCE)) {
            var redis = connection.sync();
            ScanArgs scan = ScanArgs.Builder.matches(prefix + "*").limit(200);
            // Check connectivity and SCAN permission before PostgreSQL changes.
            var firstPage = redis.scan(ScanCursor.INITIAL, scan);
            validate(firstPage.getKeys());
            resetPostgres.run();
            System.out.println("PostgreSQL reset and migration: complete");
            long removed = clear(redis, scan);
            System.out.println("Redis reset: complete (" + removed + " keys removed)");
        } finally {
            client.shutdown();
        }
    }

    private long clear(RedisCommands<byte[], byte[]> redis, ScanArgs scan) {
        ScanCursor cursor = ScanCursor.INITIAL;
        long removed = 0;
        do {
            var page = redis.scan(cursor, scan);
            validate(page.getKeys());
            for (byte[] key : page.getKeys()) {
                removed += redis.del(key);
            }
            cursor = page;
        } while (!cursor.isFinished());
        return removed;
    }

    private void validate(Iterable<byte[]> keys) {
        for (byte[] key : keys) {
            if (key.length < prefixBytes.length
                    || !Arrays.equals(key, 0, prefixBytes.length, prefixBytes, 0, prefixBytes.length)) {
                throw new IllegalStateException("Redis returned a key outside the configured namespace");
            }
        }
    }

    @FunctionalInterface
    interface SqlStep {
        void run() throws SQLException;
    }
}
