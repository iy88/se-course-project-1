package io.github.iy88.project1.messaging;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.RedisStreamCommands.XAddOptions;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class TaskStream {
    private final StringRedisTemplate redis;
    private final TaskSchedules schedules;
    private final TaskWorker worker;
    private final DeliverySettings settings;
    private final String key;
    private final String group;
    private final String consumer = UUID.randomUUID().toString();
    private boolean groupReady;

    public TaskStream(StringRedisTemplate redis, TaskSchedules schedules, TaskWorker worker, DeliverySettings settings,
                      @Value("${project1.redis.namespace}") String namespace) {
        this.redis = redis;
        this.schedules = schedules;
        this.worker = worker;
        this.settings = settings;
        key = namespace + ":work";
        group = namespace + ":workers";
    }

    @SuppressWarnings("unchecked")
    public void tick() {
        if (worker.kinds().isEmpty()) return;
        var stream = redis.<String, String>opsForStream();
        try {
            if (!groupReady) {
                try {
                    stream.createGroup(key, ReadOffset.from("0-0"), group);
                } catch (RuntimeException failure) {
                    if (!containsRedisCode(failure, "BUSYGROUP")) throw failure;
                }
                groupReady = true;
            }
            for (var due : schedules.due(worker.kinds())) {
                stream.add(key, Map.of("task_id", due.id().toString(), "task_kind", due.kind()),
                        XAddOptions.maxlen(settings.streamMaxLength()));
            }
            var idle = Duration.ofSeconds(settings.leaseSeconds());
            var pending = stream.pending(key, group, Range.unbounded(), settings.batchSize(), idle).stream()
                    .map(message -> message.getId()).toArray(RecordId[]::new);
            if (pending.length != 0) {
                consume(stream.claim(key, group, consumer, idle, pending));
            }
            var offset = StreamOffset.create(key, ReadOffset.lastConsumed());
            var options = StreamReadOptions.empty().count(settings.batchSize());
            consume(stream.read(Consumer.from(group, consumer), options, offset));
        } catch (RuntimeException failure) {
            if (containsRedisCode(failure, "NOGROUP")) groupReady = false;
            throw failure;
        }
    }

    private void consume(List<MapRecord<String, String, String>> entries) {
        if (entries == null) return;
        for (var entry : entries) {
            String kind = entry.getValue().get("task_kind");
            String id = entry.getValue().get("task_id");
            if (kind != null && id != null && worker.kinds().contains(kind)) {
                if (!worker.run(new TaskSchedules.Ready(UUID.fromString(id), kind))) continue;
                var stream = redis.<String, String>opsForStream();
                stream.acknowledge(group, entry);
                stream.delete(entry);
            }
        }
    }

    private static boolean containsRedisCode(Throwable failure, String code) {
        for (var cause = failure; cause != null; cause = cause.getCause()) {
            if (cause.getMessage() != null && cause.getMessage().contains(code)) return true;
        }
        return false;
    }
}
