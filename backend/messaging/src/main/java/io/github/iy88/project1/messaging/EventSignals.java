package io.github.iy88.project1.messaging;

import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.Limit;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class EventSignals {
    private final StringRedisTemplate redis;
    private final DeliverySettings settings;
    private final String key;

    public EventSignals(StringRedisTemplate redis, DeliverySettings settings,
                        @Value("${project1.redis.namespace}") String namespace) {
        this.redis = redis;
        this.settings = settings;
        key = namespace + ":events";
    }

    public static String wakeChannel(String namespace) {
        return namespace + ":events:wake";
    }

    public String tail() {
        var rows = redis.<String, String>opsForStream().reverseRange(key, Range.unbounded(), Limit.limit().count(1));
        return rows == null || rows.isEmpty() ? "0-0" : rows.getFirst().getId().getValue();
    }

    @SuppressWarnings("unchecked")
    public List<Signal> readAfter(String offset) {
        var rows = redis.<String, String>opsForStream().read(StreamReadOptions.empty().count(settings.batchSize()),
                StreamOffset.create(key, ReadOffset.from(offset)));
        if (rows == null) return List.of();
        return rows.stream().map(row -> new Signal(row.getId().getValue(),
                UUID.fromString(row.getValue().get("event_id")),
                Long.parseLong(row.getValue().get("recipient_account_id")),
                Long.parseLong(row.getValue().get("account_seq")))).toList();
    }

    public record Signal(String offset, UUID eventId, long accountId, long accountSequence) {}
}
