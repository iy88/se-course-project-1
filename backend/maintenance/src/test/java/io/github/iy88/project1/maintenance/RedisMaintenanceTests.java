package io.github.iy88.project1.maintenance;

import io.lettuce.core.KeyScanCursor;
import io.lettuce.core.RedisCommandExecutionException;
import io.lettuce.core.ScanArgs;
import io.lettuce.core.ScanCursor;
import io.lettuce.core.api.sync.RedisCommands;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class RedisMaintenanceTests {
    private static final String PREFIX = "maintenance:test:";
    private final RedisCommands<byte[], byte[]> redis = mock();
    private final RedisMaintenance.SqlStep postgres = mock(RedisMaintenance.SqlStep.class);

    @Test
    void scanFailureStopsBeforePostgresReset() {
        var denied = new RedisCommandExecutionException("NOPERM SCAN");
        when(redis.scan(eq(ScanCursor.INITIAL), any(ScanArgs.class))).thenThrow(denied);

        assertThatThrownBy(() -> RedisMaintenance.resetAfter(redis, PREFIX, postgres)).isSameAs(denied);

        verifyNoInteractions(postgres);
        verify(redis, never()).del(any(byte[][].class));
    }

    @Test
    void postgresFailureStopsBeforeRedisDeletion() throws SQLException {
        byte[] key = key("retained");
        var failure = new SQLException("database is in use", "55006");
        when(redis.scan(eq(ScanCursor.INITIAL), any(ScanArgs.class))).thenReturn(page("0", key));
        doThrow(failure).when(postgres).run();

        assertThatThrownBy(() -> RedisMaintenance.resetAfter(redis, PREFIX, postgres)).isSameAs(failure);

        verify(redis).scan(eq(ScanCursor.INITIAL), any(ScanArgs.class));
        verify(postgres).run();
        verify(redis, never()).del(any(byte[][].class));
    }

    @Test
    void retryAfterRedisFailureRerunsPostgresAndClearsTheRemainingKeys() throws SQLException {
        byte[] firstKey = key("already-removed");
        byte[] lastKey = key("still-present");
        var first = page("8", firstKey);
        var remaining = page("0", lastKey);
        when(redis.scan(eq(ScanCursor.INITIAL), any(ScanArgs.class)))
                .thenReturn(first).thenReturn(first).thenReturn(remaining).thenReturn(remaining);
        when(redis.scan(eq(first), any(ScanArgs.class))).thenReturn(remaining);
        var denied = new RedisCommandExecutionException("NOPERM DEL");
        when(redis.del(firstKey)).thenReturn(1L);
        when(redis.del(lastKey)).thenThrow(denied).thenReturn(1L);

        assertThatThrownBy(() -> RedisMaintenance.resetAfter(redis, PREFIX, postgres)).isSameAs(denied);
        RedisMaintenance.resetAfter(redis, PREFIX, postgres);

        var calls = inOrder(redis, postgres);
        calls.verify(redis).scan(eq(ScanCursor.INITIAL), any(ScanArgs.class));
        calls.verify(postgres).run();
        calls.verify(redis).scan(eq(ScanCursor.INITIAL), any(ScanArgs.class));
        calls.verify(redis).del(firstKey);
        calls.verify(redis).scan(eq(first), any(ScanArgs.class));
        calls.verify(redis).del(lastKey);
        calls.verify(redis).scan(eq(ScanCursor.INITIAL), any(ScanArgs.class));
        calls.verify(postgres).run();
        calls.verify(redis).scan(eq(ScanCursor.INITIAL), any(ScanArgs.class));
        calls.verify(redis).del(lastKey);
        calls.verifyNoMoreInteractions();
    }

    private static KeyScanCursor<byte[]> page(String cursor, byte[] key) {
        var page = new KeyScanCursor<byte[]>();
        page.setCursor(cursor);
        page.setFinished("0".equals(cursor));
        page.getKeys().add(key);
        return page;
    }

    private static byte[] key(String suffix) {
        return (PREFIX + suffix).getBytes(StandardCharsets.UTF_8);
    }
}
