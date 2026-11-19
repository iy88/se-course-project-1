package io.github.iy88.project1.api.realtime;

import java.util.List;
import java.util.UUID;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;

final class ConnectionQuota {
    private static final DefaultRedisScript<Long> ACQUIRE = new DefaultRedisScript<>("""
            local time = redis.call('TIME')
            local now = time[1] * 1000 + math.floor(time[2] / 1000)
            local ttl = tonumber(ARGV[2])
            for _, key in ipairs(KEYS) do
                redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
            end
            for i, key in ipairs(KEYS) do
                if not redis.call('ZSCORE', key, ARGV[1]) then
                    if ARGV[5] == 'renew' or redis.call('ZCARD', key) >= tonumber(ARGV[i + 2]) then
                        return 0
                    end
                end
            end
            for _, key in ipairs(KEYS) do
                redis.call('ZADD', key, now + ttl, ARGV[1])
                redis.call('PEXPIRE', key, ttl)
            end
            return 1
            """, Long.class);
    private static final DefaultRedisScript<Long> ACTIVE = new DefaultRedisScript<>("""
            local time = redis.call('TIME')
            local now = time[1] * 1000 + math.floor(time[2] / 1000)
            local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
            if score and tonumber(score) > now then return 1 end
            return 0
            """, Long.class);
    private final StringRedisTemplate redis;
    private final String namespace;
    private final RealtimeSettings settings;

    ConnectionQuota(StringRedisTemplate redis, String namespace, RealtimeSettings settings) {
        this.redis = redis;
        this.namespace = namespace;
        this.settings = settings;
    }

    boolean reserve(RealtimeAccess.Session session, UUID connection, boolean renewal) {
        return Long.valueOf(1).equals(redis.execute(ACQUIRE, keys(session), connection.toString(),
                Long.toString(settings.idleSeconds() * 1000L), Integer.toString(settings.accountLimit()),
                Integer.toString(settings.sessionLimit()), renewal ? "renew" : "open"));
    }

    boolean belongsTo(RealtimeAccess.Session session, UUID connection) {
        return Long.valueOf(1).equals(redis.execute(ACTIVE, List.of(keys(session).getLast()), connection.toString()));
    }

    void release(RealtimeAccess.Session session, UUID connection) {
        for (String key : keys(session)) redis.opsForZSet().remove(key, connection.toString());
    }

    private List<String> keys(RealtimeAccess.Session session) {
        String account = namespace + ":{realtime:" + session.accountId() + "}";
        return List.of(account + ":account", account + ":session:" + session.id());
    }
}
