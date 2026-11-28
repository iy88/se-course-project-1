package io.github.iy88.project1.integration;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.api.realtime.RealtimeAccess;
import io.github.iy88.project1.api.realtime.RealtimeSocket;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskHandler;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.messaging.TaskStream;
import io.github.iy88.project1.messaging.TaskWorker;
import io.github.iy88.project1.messaging.UserEvents;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.awaitility.Awaitility.await;

class InfrastructureIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final UUID SESSION_ID = UUID.randomUUID();
    private static final long ACCOUNT = ThreadLocalRandom.current().nextLong(1L << 42, 1L << 52);
    private static final long WRITE_EVENT_RECIPIENT = ACCOUNT + 1;
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String TASK_KIND = "integration-" + RUN_ID;
    private static final AtomicInteger TASK_EXECUTIONS = new AtomicInteger();
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final LockPlan EMPTY = new LockPlan(Map.of(), Set.of());
    private static final ResourceRef FIXTURE = new ResourceRef("integration", ACCOUNT);
    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static StringRedisTemplate redis;
    private static String namespace;

    @BeforeAll
    static void startApplication() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        String baseNamespace = properties.getProperty("REDIS_NAMESPACE");
        if (baseNamespace == null || baseNamespace.isBlank()) {
            throw new IllegalArgumentException("REDIS_NAMESPACE is required");
        }
        namespace = baseNamespace + ":integration:" + RUN_ID;
        properties.setProperty("REDIS_NAMESPACE", namespace);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("EVENT_HEAD_POLL_SECONDS", "1");
        properties.setProperty("WORK_LEASE_SECONDS", "3");
        properties.setProperty("WORK_IO_TIMEOUT_SECONDS", "1");
        properties.setProperty("WORK_BATCH_SIZE", "32");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        var application = new SpringApplication(BackendAppApplication.class, Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("integration", properties)));
        app = application.run("--spring.profiles.active=infrastructure",
                "--server.port=0", "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        redis = app.getBean(StringRedisTemplate.class);
        assertThat(app.getEnvironment().getProperty("project1.redis.namespace")).isEqualTo(namespace);
    }

    @AfterAll
    static void cleanUp() {
        if (app == null) return;
        try (var _ = app) {
            db.sql("DELETE FROM user_event WHERE recipient_account_id IN (?, ?)")
                    .param(ACCOUNT).param(WRITE_EVENT_RECIPIENT).update();
            db.sql("DELETE FROM account_event_head WHERE account_id IN (?, ?)")
                    .param(ACCOUNT).param(WRITE_EVENT_RECIPIENT).update();
            db.sql("DELETE FROM task_schedule WHERE task_kind = ?").param(TASK_KIND).update();
            db.sql("DELETE FROM audit_record WHERE actor_kind = 'account' AND actor_id = ?")
                    .param(Long.toString(ACCOUNT)).update();
            db.sql("DELETE FROM operation_record WHERE actor_kind = 'account' AND actor_id = ?")
                    .param(Long.toString(ACCOUNT)).update();
            db.sql("DELETE FROM operation_record WHERE actor_kind = 'system' AND actor_id = ?")
                    .param(TASK_KIND).update();
            redis.delete(List.of(namespace + ":work", namespace + ":events", namespace + ":{realtime:" + ACCOUNT + "}:account",
                    namespace + ":{realtime:" + ACCOUNT + "}:session:" + SESSION_ID));
        }
    }

    @Test
    void concurrentWritesHoldAccountLocksAndReplayTheCommittedOperation() throws Exception {
        var writes = app.getBean(WriteExecutor.class);
        var writing = new CountDownLatch(1);
        var secondQualified = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var concurrentWrites = new AtomicInteger();
        String key = RUN_ID.toString();
        var first = new WriteFixture() {
            @Override
            public WriteResult.Response<?> write(WriteTransaction transaction, String request, Boolean qualification,
                                                 LockPlan plan) {
                concurrentWrites.incrementAndGet();
                writing.countDown();
                waitFor(release);
                return super.write(transaction, request, qualification, plan);
            }
        };
        var second = new WriteFixture() {
            @Override
            public Boolean qualify(ExecutionContext context, String request, LockPlan plan) {
                secondQualified.countDown();
                return true;
            }

            @Override
            public WriteResult.Response<?> write(WriteTransaction transaction, String request, Boolean qualification,
                                                 LockPlan plan) {
                concurrentWrites.incrementAndGet();
                return super.write(transaction, request, qualification, plan);
            }
        };

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var original = executor.submit(() -> writes.run(accountContext(), "integration.write", key, "first", first));
            try {
                waitFor(writing);
                assertThat(db.sql("SELECT pg_try_advisory_xact_lock(?)").param(ACCOUNT).query(Boolean.class).single())
                        .isFalse();
                var retried = executor.submit(() ->
                        writes.run(accountContext(), "integration.write", key, "first", second));
                waitFor(secondQualified);
                assertThat(retried.isDone()).isFalse();
                release.countDown();

                var committed = original.get(5, TimeUnit.SECONDS);
                var replay = retried.get(5, TimeUnit.SECONDS);
                assertThat(committed.replayed()).isFalse();
                assertThat(replay.replayed()).isTrue();
                assertThat(replay.operationId()).isEqualTo(committed.operationId());
                assertThat(replay.data()).isEqualTo(committed.data());
                assertThat(concurrentWrites.get()).isEqualTo(1);
                assertThat(auditCount(committed.operationId())).isEqualTo(1);
            } finally {
                release.countDown();
            }
        }
    }

    @Test
    void rollingBackAWriteReleasesTheIdempotencyKeyAndRemovesItsAudit() {
        var writes = app.getBean(WriteExecutor.class);
        String key = RUN_ID + "-rollback";
        var failing = new WriteFixture() {
            @Override
            public WriteResult.Response<?> write(WriteTransaction transaction, String request, Boolean qualification,
                                                 LockPlan plan) {
                super.write(transaction, request, qualification, plan);
                throw new BusinessError("INTEGRATION_ROLLBACK", 409, "fixture");
            }
        };
        assertThatThrownBy(() -> writes.run(accountContext(), "integration.rollback", key, "before", failing))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("INTEGRATION_ROLLBACK");
                    assertThat(auditCount(error.operationId())).isZero();
                });
        var result = writes.run(accountContext(), "integration.rollback", key, "after", new WriteFixture());
        assertThat(result.replayed()).isFalse();
        assertThat(result.data().path("value").stringValue()).isEqualTo("after");
        assertThat(auditCount(result.operationId())).isEqualTo(1);
    }

    @Test
    void eventPersistenceFailureRollsBackAuditCursorAndIdempotencyReservation() {
        var writes = app.getBean(WriteExecutor.class);
        var events = app.getBean(UserEvents.class);
        String key = RUN_ID + "-event";
        var command = new WriteFixture() {
            @Override
            public WriteResult.Response<?> write(WriteTransaction transaction, String request, Boolean qualification,
                                                 LockPlan plan) {
                var response = super.write(transaction, request, qualification, plan);
                transaction.addEventIntent(Set.of(WRITE_EVENT_RECIPIENT), "integration_changed", 1, FIXTURE,
                        key, null, null);
                if ("duplicate".equals(request)) {
                    transaction.addEventIntent(Set.of(WRITE_EVENT_RECIPIENT), "integration_changed", 1, FIXTURE,
                            key, null, null);
                }
                return response;
            }
        };

        assertThatThrownBy(() -> writes.run(accountContext(), "integration.event", key, "duplicate", command))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("EVENT_INTENT_CONFLICT");
                    assertThat(auditCount(error.operationId())).isZero();
                });
        assertThat(events.head(WRITE_EVENT_RECIPIENT).headSequence()).isZero();

        var recovered = writes.run(accountContext(), "integration.event", key, "recovered", command);
        var head = events.head(WRITE_EVENT_RECIPIENT);
        var page = events.scan(WRITE_EVENT_RECIPIENT, head.epoch(), 0, 10);
        assertThat(recovered.replayed()).isFalse();
        assertThat(auditCount(recovered.operationId())).isEqualTo(1);
        assertThat(page.events()).singleElement().satisfies(event -> {
            assertThat(event.sequence()).isEqualTo(1);
            assertThat(event.type()).isEqualTo("integration_changed");
        });
    }

    @Test
    @SuppressWarnings("unchecked")
    void workerReclaimsThePendingMessageAndExpiredDatabaseLeaseAfterAnInterruptedAttempt() {
        var schedule = app.getBean(TaskSchedules.class);
        var tx = app.getBean(TransactionTemplate.class);
        var task = tx.execute(status -> schedule.schedule(new TaskSchedules.Spec(TASK_KIND, FIXTURE,
                RUN_ID.toString(), "v1", Instant.now().minusSeconds(1), "integration")));
        assertThat(task).isNotNull();
        String key = namespace + ":work";
        String group = namespace + ":workers";
        var stream = redis.<String, String>opsForStream();
        var tasks = app.getBean(TaskStream.class);
        tasks.enqueueDue();
        assertThat(stream.size(key)).isEqualTo(1);
        stream.createGroup(key, ReadOffset.from("0-0"), group);
        var delivered = stream.read(Consumer.from(group, "stopped-worker"), StreamReadOptions.empty().count(1),
                StreamOffset.create(key, ReadOffset.lastConsumed()));
        assertThat(delivered).singleElement().satisfies(entry -> assertThat(entry.getValue())
                .containsExactlyInAnyOrderEntriesOf(Map.of("task_id", task.id().toString(), "task_kind", TASK_KIND)));
        var interrupted = schedule.claim(new TaskSchedules.Ready(task.id(), TASK_KIND)).orElseThrow();
        assertThat(interrupted.attempt()).isEqualTo(1);
        assertThat(schedule.claim(new TaskSchedules.Ready(task.id(), TASK_KIND))).isEmpty();
        await().atMost(Duration.ofSeconds(10)).until(() ->
                stream.pending(key, group, Range.unbounded(), 1, Duration.ofSeconds(3)).size() == 1
                        && db.sql("SELECT lease_until <= clock_timestamp() FROM task_schedule WHERE task_id = ?")
                                .param(task.id()).query(Boolean.class).single());

        tasks.consume();

        assertThat(stream.pending(key, group).getTotalPendingMessages()).isZero();
        assertThat(stream.size(key)).isZero();
        assertThat(TASK_EXECUTIONS.get()).isEqualTo(1);
        assertThat(db.sql("SELECT completed_at IS NOT NULL FROM task_schedule WHERE task_id = ?")
                .param(task.id()).query(Boolean.class).single()).isTrue();
        assertThat(db.sql("SELECT attempts FROM task_schedule WHERE task_id = ?")
                .param(task.id()).query(Integer.class).single()).isEqualTo(2);
        assertThat(schedule.retry(interrupted, "LATE_WORKER")).isFalse();
    }

    @Test
    void workerPersistsRetryAndCancelsAnObsoleteTaskWithoutExecutingIt() {
        var schedules = app.getBean(TaskSchedules.class);
        var worker = app.getBean(TaskWorker.class);
        var transaction = app.getBean(TransactionTemplate.class);
        var retry = transaction.execute(status -> schedules.schedule(new TaskSchedules.Spec(TASK_KIND, FIXTURE,
                RUN_ID + "-retry", "v1", Instant.now().minusSeconds(1), "integration")));
        var obsolete = transaction.execute(status -> schedules.schedule(new TaskSchedules.Spec(TASK_KIND, FIXTURE,
                RUN_ID + "-obsolete", "v1", Instant.now().minusSeconds(1), "integration")));

        int executions = TASK_EXECUTIONS.get();
        assertThat(worker.run(new TaskSchedules.Ready(retry.id(), TASK_KIND))).isTrue();
        assertThat(db.sql("""
                SELECT attempts = 1 AND last_error = 'INTEGRATION_RETRY' AND lease_token IS NULL
                    AND completed_at IS NULL AND next_attempt_at > due_at
                FROM task_schedule WHERE task_id = ?
                """).param(retry.id()).query(Boolean.class).single()).isTrue();
        db.sql("DELETE FROM task_schedule WHERE task_id = ?").param(retry.id()).update();

        var ready = new TaskSchedules.Ready(obsolete.id(), TASK_KIND);
        assertThat(worker.run(ready)).isTrue();
        assertThat(worker.run(ready)).isTrue();
        assertThat(db.sql("""
                SELECT attempts = 1 AND cancelled_at IS NOT NULL AND completed_at IS NULL
                FROM task_schedule WHERE task_id = ?
                """).param(obsolete.id()).query(Boolean.class).single()).isTrue();
        assertThat(TASK_EXECUTIONS.get()).isEqualTo(executions);
    }

    @Test
    void replayRechecksAccessAndPreservesTheOriginalOperation() {
        var writes = app.getBean(WriteExecutor.class);
        String key = RUN_ID + "-replay-access";
        var committed = writes.run(accountContext(), "integration.access", key, "value", new WriteFixture());
        var denied = new WriteFixture() {
            @Override
            public void requireReplayAccess(ExecutionContext context, Boolean qualified, ResourceRef resource) {
                assertThat(resource).isEqualTo(FIXTURE);
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "fixture");
            }
        };
        assertThatThrownBy(() -> writes.run(accountContext(), "integration.access", key, "value", denied))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE");
                    assertThat(error.operationId()).isEqualTo(committed.operationId());
                });
        var replay = writes.run(accountContext(), "integration.access", key, "value", new WriteFixture());
        assertThat(replay.replayed()).isTrue();
        assertThat(replay.operationId()).isEqualTo(committed.operationId());
        assertThat(auditCount(committed.operationId())).isEqualTo(1);
    }

    @Test
    void websocketReconnectReplaysOnlyTheEventsAfterTheAcknowledgedCursor() throws Exception {
        var events = app.getBean(UserEvents.class);
        var tx = app.getBean(TransactionTemplate.class);
        tx.executeWithoutResult(status -> events.persist(accountContext(), List.of(event("first"))));
        var epoch = events.head(ACCOUNT).epoch().toString();
        int port = ((WebServerApplicationContext) app).getWebServer().getPort();
        await().atMost(Duration.ofSeconds(10)).until(() -> app.getBean(RealtimeSocket.class).accepting());

        try (var client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
             var first = Connection.open(client, port)) {
            first.send(hello(epoch, 0));
            first.receive("hello_ok");
            assertThat(first.receive("event").path("account_seq").asLong()).isEqualTo(1);
            first.send(Map.of("type", "ack", "epoch", epoch, "through_seq", 1));
            first.send(Map.of("type", "ping", "nonce", "first"));
            assertThat(first.receive("pong").path("nonce").stringValue()).isEqualTo("first");
        }
        var secondEvent = event("second");
        tx.executeWithoutResult(status -> events.persist(accountContext(), List.of(secondEvent)));
        try (var client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
             var next = Connection.open(client, port)) {
            next.send(hello(epoch, 1));
            next.receive("hello_ok");
            var replay = next.receive("event");
            assertThat(replay.path("account_seq").asLong()).isEqualTo(2);
            assertThat(replay.path("event_id").stringValue()).isEqualTo(secondEvent.eventId().toString());
        }
    }

    private static long auditCount(UUID operation) {
        return db.sql("SELECT count(*) FROM audit_record WHERE operation_id = ?").param(operation).query(Long.class).single();
    }

    private static ExecutionContext accountContext() {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(ACCOUNT),
                SESSION_ID, null, 1L, "integration");
    }

    private static EventIntent event(String key) {
        return new EventIntent(UUID.randomUUID(), ACCOUNT, "integration_changed", 1, FIXTURE, RUN_ID + ":" + key, null, null);
    }

    private static Map<String, ?> hello(String epoch, long after) {
        return Map.of("type", "hello", "protocol_version", 1, "csrf_token", RUN_ID.toString(),
                "cursor", Map.of("epoch", epoch, "after_seq", after));
    }

    private static void waitFor(CountDownLatch latch) {
        try {
            assertThat(latch.await(5, TimeUnit.SECONDS)).isTrue();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new AssertionError(interrupted);
        }
    }

    static class WriteFixture implements WriteExecutor.UseCase<String, Boolean> {
        @Override
        public JsonNode digestInput(String request) { return JSON.createObjectNode().put("value", request); }

        @Override
        public LockPlan prepare(ExecutionContext context, String request) { return EMPTY; }

        @Override
        public Boolean qualify(ExecutionContext context, String request, LockPlan plan) { return true; }

        @Override
        public void requireReplayAccess(ExecutionContext context, Boolean qualified, ResourceRef resource) {}

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, String request, Boolean qualified, LockPlan plan) {
            transaction.audit("integration.write", FIXTURE, null, JSON.createObjectNode());
            return new WriteResult.Response<>(200, Map.of("value", request), FIXTURE);
        }
    }

    @TestConfiguration(proxyBeanMethods = false)
    public static class Fixtures {
        @Bean
        @Primary
        public RealtimeAccess infrastructureRealtimeAccess() {
            return new RealtimeAccess() {
                @Override
                public Session authenticate(HttpServletRequest request) {
                    var cookies = request.getCookies();
                    if (cookies == null || Arrays.stream(cookies).noneMatch(cookie ->
                            "it_session".equals(cookie.getName()) && SESSION_ID.toString().equals(cookie.getValue()))) {
                        throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "fixture");
                    }
                    return new Session(ACCOUNT, SESSION_ID, 1, "integration");
                }

                @Override
                public void requireCurrent(Session session) {}

                @Override
                public void requireHello(Session session, String csrfToken) {
                    if (!RUN_ID.toString().equals(csrfToken)) throw new BusinessError("CSRF_INVALID", 403, "fixture");
                }

                @Override
                public Optional<Map<String, ?>> project(ExecutionContext context, UserEvents.Event event) {
                    return Optional.of(Map.of("source_id", event.source().id()));
                }
            };
        }

        @Bean
        public TaskHandler integrationTaskHandler() {
            return new TaskHandler() {
                @Override
                public String kind() { return TASK_KIND; }

                @Override
                public LockPlan prepare(ExecutionContext context, TaskSchedules.Task task) { return EMPTY; }

                @Override
                public void lockAndQualify(WriteTransaction transaction, TaskSchedules.Task task) {}

                @Override
                public boolean isApplicable(TaskSchedules.Task task) {
                    return !task.spec().triggerKey().equals(RUN_ID + "-obsolete");
                }

                @Override
                public void execute(WriteTransaction transaction, TaskSchedules.Task task) {
                    if (task.spec().triggerKey().equals(RUN_ID + "-retry")) {
                        throw new BusinessError("INTEGRATION_RETRY", 409, "fixture");
                    }
                    TASK_EXECUTIONS.incrementAndGet();
                }
            };
        }
    }

    static final class Connection implements WebSocket.Listener, AutoCloseable {
        private final BlockingQueue<JsonNode> frames = new LinkedBlockingQueue<>();
        private final StringBuilder buffer = new StringBuilder();
        private WebSocket socket;

        static Connection open(HttpClient client, int port) {
            var connection = new Connection();
            connection.socket = client.newWebSocketBuilder().connectTimeout(Duration.ofSeconds(5))
                    .header("Origin", ORIGIN).header("Cookie", "it_session=" + SESSION_ID)
                    .buildAsync(URI.create("ws://127.0.0.1:" + port + "/api/v1/realtime"), connection)
                    .orTimeout(5, TimeUnit.SECONDS).join();
            return connection;
        }

        @Override
        public CompletionStage<?> onText(WebSocket source, CharSequence data, boolean last) {
            buffer.append(data);
            if (last) {
                var frame = JSON.readTree(buffer.toString());
                buffer.setLength(0);
                if ("ping".equals(frame.path("type").stringValue())) {
                    source.sendText(JSON.writeValueAsString(Map.of("type", "pong", "nonce", frame.path("nonce").stringValue())), true);
                } else {
                    frames.add(frame);
                }
            }
            source.request(1);
            return null;
        }

        void send(Map<String, ?> frame) {
            socket.sendText(JSON.writeValueAsString(frame), true).orTimeout(5, TimeUnit.SECONDS).join();
        }

        JsonNode receive(String type) throws InterruptedException {
            var frame = frames.poll(8, TimeUnit.SECONDS);
            assertThat(frame).as("WebSocket frame %s", type).isNotNull();
            assertThat(frame.path("type").stringValue()).isEqualTo(type);
            return frame;
        }

        @Override
        public void close() {
            socket.sendClose(WebSocket.NORMAL_CLOSURE, "").orTimeout(2, TimeUnit.SECONDS).join();
            socket.abort();
        }
    }
}
