package io.github.iy88.project1.messaging;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessage;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class TaskStreamTests {
    private static final String KEY = "test:work";
    private static final String GROUP = "test:workers";
    private static final StreamOffset<String> OFFSET = StreamOffset.create(KEY, ReadOffset.lastConsumed());
    private static final String KIND = "expire-trade";
    private static final int BATCH_SIZE = 10;
    private static final Duration LEASE = Duration.ofSeconds(30);
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    private final StreamOperations<String, String, String> stream = mock();
    private final TaskSchedules schedules = mock(TaskSchedules.class);
    private final TaskWorker worker = mock(TaskWorker.class);
    private final TaskStream tasks = new TaskStream(redis, schedules, worker,
            new DeliverySettings(3600, 10, 30, 5, 3, 1, BATCH_SIZE, 100), "test");

    @BeforeEach
    void configureStream() {
        when(redis.<String, String>opsForStream()).thenReturn(stream);
        when(worker.kinds()).thenReturn(Set.of(KIND));
        when(stream.pending(KEY, GROUP, Range.unbounded(), BATCH_SIZE, LEASE))
                .thenReturn(new PendingMessages(GROUP, List.of()));
    }

    @Test
    void acknowledgesOnlyEntriesTheWorkerCanDiscard() {
        var ready = new TaskSchedules.Ready(UUID.randomUUID(), KIND);
        var busy = new TaskSchedules.Ready(UUID.randomUUID(), KIND);
        var unrelated = new TaskSchedules.Ready(UUID.randomUUID(), "other");
        var completedEntry = entry(ready, "1-0");
        var pendingEntry = entry(busy, "2-0");
        var unrelatedEntry = entry(unrelated, "3-0");
        receive(List.of(completedEntry, pendingEntry, unrelatedEntry));
        when(worker.run(ready)).thenReturn(true);

        tasks.tick();

        verify(worker).run(ready);
        verify(worker).run(busy);
        verify(worker, never()).run(unrelated);
        verify(stream).acknowledge(GROUP, completedEntry);
        verify(stream).delete(completedEntry);
        verify(stream, never()).acknowledge(GROUP, pendingEntry);
        verify(stream, never()).delete(pendingEntry);
        verify(stream, never()).acknowledge(GROUP, unrelatedEntry);
    }

    @Test
    @SuppressWarnings("unchecked")
    void claimsAnIdleEntryBeforeReadingNewMessages() {
        var ready = new TaskSchedules.Ready(UUID.randomUUID(), KIND);
        var entry = entry(ready, "1-0");
        var pending = new PendingMessage(entry.getId(), Consumer.from(GROUP, "previous-worker"), LEASE, 1);
        when(stream.pending(KEY, GROUP, Range.unbounded(), BATCH_SIZE, LEASE))
                .thenReturn(new PendingMessages(GROUP, List.of(pending)));
        when(stream.claim(eq(KEY), eq(GROUP), anyString(), eq(LEASE), eq(entry.getId()))).thenReturn(List.of(entry));
        when(worker.run(ready)).thenReturn(true);

        tasks.tick();

        var order = inOrder(stream);
        order.verify(stream).claim(eq(KEY), eq(GROUP), anyString(), eq(LEASE), eq(entry.getId()));
        order.verify(stream).acknowledge(GROUP, entry);
        order.verify(stream).read(any(Consumer.class), any(StreamReadOptions.class), eq(OFFSET));
    }

    @Test
    void recreatesTheGroupAfterRedisReportsItMissing() {
        when(stream.createGroup(KEY, ReadOffset.from("0-0"), GROUP))
                .thenThrow(new IllegalStateException("BUSYGROUP")).thenReturn("OK");
        var missing = new IllegalStateException("NOGROUP");
        when(stream.pending(KEY, GROUP, Range.unbounded(), BATCH_SIZE, LEASE))
                .thenThrow(missing).thenReturn(new PendingMessages(GROUP, List.of()));

        assertThatThrownBy(tasks::tick).isSameAs(missing);
        tasks.tick();

        verify(stream, times(2)).createGroup(KEY, ReadOffset.from("0-0"), GROUP);
    }

    @Test
    void skipsStreamAccessWithoutRegisteredHandlers() {
        when(worker.kinds()).thenReturn(Set.of());

        tasks.tick();

        verifyNoInteractions(stream, schedules);
    }

    @SuppressWarnings("unchecked")
    private void receive(List<MapRecord<String, String, String>> records) {
        when(stream.read(any(Consumer.class), any(StreamReadOptions.class), eq(OFFSET))).thenReturn(records);
    }

    private static MapRecord<String, String, String> entry(TaskSchedules.Ready ready, String id) {
        return MapRecord.create(KEY, Map.of("task_id", ready.id().toString(), "task_kind", ready.kind()))
                .withId(RecordId.of(id));
    }
}
