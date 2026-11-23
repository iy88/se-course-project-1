package io.github.iy88.project1.integration;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.api.realtime.OriginConnectionLookup;
import io.github.iy88.project1.api.realtime.RealtimeAccess;
import io.github.iy88.project1.api.realtime.RealtimeSessions;
import io.github.iy88.project1.api.realtime.RealtimeSocket;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.EventDispatch;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationKind;
import io.github.iy88.project1.messaging.RealtimeEventSources.ConversationRef;
import io.github.iy88.project1.messaging.UserEvents;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationQueries;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayDeque;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.Queue;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

class BusinessRealtimeIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final UUID SESSION_A1 = UUID.randomUUID();
    private static final UUID SESSION_A2 = UUID.randomUUID();
    private static final UUID SESSION_B = UUID.randomUUID();
    private static final long ACCOUNT_A = ThreadLocalRandom.current().nextLong(1L << 42, 1L << 52);
    private static final long ACCOUNT_B = ACCOUNT_A + 1;
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String CSRF = RUN_ID.toString();
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private static final Controlled SOURCES = new Controlled();
    private static final LockPlan EMPTY = new LockPlan(Map.of(), Set.of());

    private static Properties environment;
    private static String namespace;
    private static ConfigurableApplicationContext first;
    private static ConfigurableApplicationContext second;

    @BeforeAll
    static void startApplications() throws Exception {
        environment = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            environment.load(reader);
        }
        if (!"dev".equals(environment.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        String baseNamespace = environment.getProperty("REDIS_NAMESPACE");
        if (baseNamespace == null || baseNamespace.isBlank()) {
            throw new IllegalArgumentException("REDIS_NAMESPACE is required");
        }
        namespace = baseNamespace + ":business-it:" + RUN_ID;

        first = start();
        second = start();
        await().atMost(Duration.ofSeconds(20)).until(() ->
                first.getBean(RealtimeSocket.class).accepting()
                        && second.getBean(RealtimeSocket.class).accepting());
    }

    @BeforeEach
    void restoreSessions() {
        SOURCES.addSession(SESSION_A1, ACCOUNT_A);
        SOURCES.addSession(SESSION_A2, ACCOUNT_A);
        SOURCES.addSession(SESSION_B, ACCOUNT_B);
    }

    @AfterAll
    static void stopApplications() {
        try {
            var db = first == null ? null : first.getBean(JdbcClient.class);
            var redis = first == null ? null : first.getBean(StringRedisTemplate.class);
            if (db != null) {
                db.sql("DELETE FROM notification WHERE recipient_account_id IN (?, ?) AND intent_key LIKE ?")
                        .param(ACCOUNT_A).param(ACCOUNT_B).param("realtime:" + RUN_ID + ":%").update();
                db.sql("DELETE FROM user_event WHERE recipient_account_id IN (?, ?)")
                        .param(ACCOUNT_A).param(ACCOUNT_B).update();
                db.sql("DELETE FROM account_event_head WHERE account_id IN (?, ?)")
                        .param(ACCOUNT_A).param(ACCOUNT_B).update();
                db.sql("DELETE FROM operation_record WHERE actor_kind = 'account' AND actor_id IN (?, ?)")
                        .param(Long.toString(ACCOUNT_A)).param(Long.toString(ACCOUNT_B)).update();
            }
            if (redis != null) {
                var keys = redis.keys(namespace + "*");
                if (keys != null && !keys.isEmpty()) redis.delete(keys);
            }
        } finally {
            SOURCES.clear();
            close(second);
            close(first);
        }
    }

    @Test
    void sameAccountReceivesHintsOnBothInstancesAndAnotherAccountStaysIsolated() throws Exception {
        try (var a1 = open(first, SESSION_A1); var a2 = open(second, SESSION_A2);
             var b = open(first, SESSION_B)) {
            helloAtHead(a1, first, ACCOUNT_A);
            helloAtHead(a2, second, ACCOUNT_A);
            helloAtHead(b, first, ACCOUNT_B);
            var created = createNotifications(first, "realtime:" + RUN_ID + ":same");
            assertThat(created.size()).isEqualTo(2);
            long firstNotification = created.path(Long.toString(ACCOUNT_A)).asLong();
            long secondNotification = created.path(Long.toString(ACCOUNT_B)).asLong();
            assertThat(firstNotification).isPositive().isNotEqualTo(secondNotification);
            assertThat(secondNotification).isPositive();
            dispatch(first);

            var one = a1.receiveEvent();
            var two = a2.receiveEvent();
            var other = b.receiveEvent();
            assertThat(one.path("event_type").stringValue()).isEqualTo("notification_created");
            assertThat(two.path("event_id").stringValue()).isEqualTo(one.path("event_id").stringValue());
            assertThat(two.path("account_seq").asLong()).isEqualTo(one.path("account_seq").asLong());
            assertThat(one.path("data").size()).isEqualTo(1);
            assertThat(one.path("data").path("notification_id").stringValue())
                    .isEqualTo(Long.toString(firstNotification));
            assertThat(one.path("data").path("summary").isMissingNode()).isTrue();
            assertThat(two.path("data").size()).isEqualTo(1);
            assertThat(two.path("data").path("notification_id").stringValue())
                    .isEqualTo(Long.toString(firstNotification));
            assertThat(two.path("data").path("summary").isMissingNode()).isTrue();
            assertThat(other.path("data").size()).isEqualTo(1);
            assertThat(other.path("data").path("notification_id").stringValue())
                    .isEqualTo(Long.toString(secondNotification));
            assertThat(other.path("data").path("summary").isMissingNode()).isTrue();
            assertThat(a1.noFrame(Duration.ofSeconds(1))).isTrue();

            var queries = first.getBean(NotificationQueries.class);
            var view = queries.get(context(ACCOUNT_A, SESSION_A1), firstNotification);
            assertThat(view.notificationId()).isEqualTo(firstNotification);
            assertThat(view.source()).isNull();

            long isolatedSequence = other.path("account_seq").asLong();
            persist(first, context(ACCOUNT_B, SESSION_B), List.of(
                    notificationCreated(ACCOUNT_B, firstNotification, "isolated:b:" + RUN_ID)));
            dispatch(first);
            var advance = b.receiveEvent();
            assertThat(advance.path("type").stringValue()).isEqualTo("cursor_advance");
            assertThat(advance.path("from_seq").asLong()).isEqualTo(isolatedSequence + 1);
            assertThat(advance.path("through_seq").asLong()).isEqualTo(isolatedSequence + 1);
            assertThat(advance.path("event_type").isMissingNode()).isTrue();
            assertThat(advance.path("data").isMissingNode()).isTrue();
            assertThat(advance.path("notification_id").isMissingNode()).isTrue();
        }
    }

    @Test
    void duplicateAndOutOfOrderSignalsStillAdvanceInDatabaseSequenceOrder() throws Exception {
        try (var a1 = open(first, SESSION_A1); var a2 = open(second, SESSION_A2)) {
            helloAtHead(a1, first, ACCOUNT_A);
            helloAtHead(a2, second, ACCOUNT_A);
            var events = first.getBean(UserEvents.class);
            long before = events.head(ACCOUNT_A).headSequence();
            var ids = List.of(createNotification(first, ACCOUNT_A), createNotification(first, ACCOUNT_A),
                    createNotification(first, ACCOUNT_A));
            persist(first, context(ACCOUNT_A, SESSION_A1), List.of(
                    notificationCreated(ACCOUNT_A, ids.get(0), "order:1:" + RUN_ID),
                    notificationCreated(ACCOUNT_A, ids.get(1), "order:2:" + RUN_ID),
                    notificationCreated(ACCOUNT_A, ids.get(2), "order:3:" + RUN_ID)));
            var page = events.scan(ACCOUNT_A, events.head(ACCOUNT_A).epoch(), before, 10);
            assertThat(page.events()).hasSize(3);
            var rows = page.events();

            var stream = first.getBean(StringRedisTemplate.class).opsForStream();
            for (int index = rows.size() - 1; index >= 0; index--) {
                var row = rows.get(index);
                stream.add(namespace + ":events", Map.of("event_id", row.eventId().toString(),
                        "recipient_account_id", Long.toString(ACCOUNT_A),
                        "account_seq", Long.toString(row.sequence())));
            }

            for (var connection : List.of(a1, a2)) {
                for (var row : rows) {
                    var frame = connection.receiveEvent();
                    assertThat(frame.path("account_seq").asLong()).isEqualTo(row.sequence());
                    assertThat(frame.path("event_id").stringValue()).isEqualTo(row.eventId().toString());
                    assertThat(frame.path("data").path("notification_id").stringValue())
                            .isEqualTo(Long.toString(ids.get((int) (row.sequence() - before - 1))));
                }
            }

            var duplicate = rows.getFirst();
            stream.add(namespace + ":events", Map.of("event_id", duplicate.eventId().toString(),
                    "recipient_account_id", Long.toString(ACCOUNT_A),
                    "account_seq", Long.toString(duplicate.sequence())));
            assertThat(a1.noFrame(Duration.ofSeconds(1))).isTrue();
            assertThat(a2.noFrame(Duration.ofSeconds(1))).isTrue();
        }
    }

    @Test
    void currentVisibilityOriginReadsAndAcknowledgementsStayTransportOnly() throws Exception {
        var conversation = SOURCES.conversation(ConversationKind.CHAT, ACCOUNT_A);
        long firstMessage = conversation.message(7, null);
        long secondMessage = conversation.message(8, null);
        long notification = createNotification(first, ACCOUNT_A);

        try (var origin = open(first, SESSION_A1); var other = open(second, SESSION_A2)) {
            var originHello = helloAtHead(origin, first, ACCOUNT_A);
            helloAtHead(other, second, ACCOUNT_A);

            persist(first, context(ACCOUNT_A, SESSION_A1), List.of(
                    messageCreated(ACCOUNT_A, conversation, firstMessage, "visible:" + RUN_ID)));
            dispatch(first);

            var visible = origin.receiveEvent();
            assertThat(visible.path("event_type").stringValue()).isEqualTo("message_created");
            assertThat(visible.path("data").size()).isEqualTo(4);
            assertThat(visible.path("data").path("conversation_kind").stringValue()).isEqualTo("chat");
            assertThat(visible.path("data").path("message_id").stringValue()).isEqualTo(Long.toString(firstMessage));
            assertThat(visible.path("data").path("message_seq").asLong()).isEqualTo(7);
            assertThat(visible.path("data").path("body").isMissingNode()).isTrue();
            assertThat(other.receiveEvent().path("account_seq").asLong())
                    .isEqualTo(visible.path("account_seq").asLong());

            conversation.readable(false);
            persist(first, context(ACCOUNT_A, SESSION_A1), List.of(
                    messageCreated(ACCOUNT_A, conversation, secondMessage, "hidden:" + RUN_ID)));
            dispatch(first);
            var hidden = origin.receiveEvent();
            assertThat(hidden.path("type").stringValue()).isEqualTo("cursor_advance");
            assertThat(hidden.path("from_seq").asLong()).isEqualTo(hidden.path("through_seq").asLong());
            assertThat(hidden.path("event_type").isMissingNode()).isTrue();
            assertThat(hidden.path("data").isMissingNode()).isTrue();
            assertThat(other.receiveEvent().path("type").stringValue()).isEqualTo("cursor_advance");
            long hiddenSequence = hidden.path("through_seq").asLong();

            conversation.readable(true);
            Instant readAt = Instant.now().minusSeconds(5).truncatedTo(ChronoUnit.MICROS);
            setNotificationReadAt(first, notification, readAt);
            var suppliedConnection = originHello.path("connection_id").stringValue();
            var lookup = second.getBean(OriginConnectionLookup.class);
            var ownerSession = new RealtimeAccess.Session(ACCOUNT_A, SESSION_A1, 1L, "business-it");
            var otherSession = new RealtimeAccess.Session(ACCOUNT_A, SESSION_A2, 1L, "business-it");
            assertThat(lookup.resolve(otherSession, suppliedConnection)).isEmpty();
            var verifiedConnection = lookup.resolve(ownerSession, suppliedConnection);
            assertThat(verifiedConnection).contains(UUID.fromString(suppliedConnection));
            persist(second, context(ACCOUNT_A, SESSION_A1, verifiedConnection.orElseThrow()), List.of(
                    notificationRead(ACCOUNT_A, notification, "notification-read:" + RUN_ID)));
            dispatch(first);

            var originAdvance = origin.receiveEvent();
            assertThat(originAdvance.path("type").stringValue()).isEqualTo("cursor_advance");
            var readHint = other.receiveEvent();
            assertThat(readHint.path("event_type").stringValue()).isEqualTo("notification_read");
            assertThat(readHint.path("data").path("notification_id").stringValue())
                    .isEqualTo(Long.toString(notification));
            assertThat(Instant.parse(readHint.path("data").path("read_at").stringValue())).isEqualTo(readAt);

            other.send(Map.of("type", "ack", "epoch", readHint.path("epoch").stringValue(),
                    "through_seq", readHint.path("account_seq").asLong()));
            var nonce = UUID.randomUUID().toString();
            other.send(Map.of("type", "ping", "nonce", nonce));
            assertThat(other.receiveType("pong").path("nonce").stringValue()).isEqualTo(nonce);
            assertThat(storedNotificationReadAt(first, notification)).isEqualTo(readAt);

            conversation.readable(false);
            var replay = request(first, "/api/v1/account/events?epoch="
                    + readHint.path("epoch").stringValue() + "&after_seq=" + (hiddenSequence - 1)
                    + "&limit=10", SESSION_A1);
            assertThat(replay.path("items").get(0).path("type").stringValue()).isEqualTo("cursor_advance");
            assertThat(replay.path("items").get(0).path("event_type").isMissingNode()).isTrue();
            assertThat(replay.path("items").get(0).path("data").isMissingNode()).isTrue();

            SOURCES.revoke(SESSION_A1);
            assertThat(requestStatus(first, "/api/v1/account/events/head", SESSION_A1)).isEqualTo(401);
            assertThat(requestStatus(first, "/api/v1/capabilities", SESSION_A1)).isEqualTo(401);
            assertThat(origin.receiveType("auth_required")).isNotNull();
            assertThat(origin.closeCode.get(5, TimeUnit.SECONDS)).isEqualTo(4401);
        }
    }

    @Test
    void coldStartResetsThenLoadsCapabilitiesHeadAndConcurrentEvents() throws Exception {
        try (var connection = open(first, SESSION_A1)) {
            var staleEpoch = UUID.randomUUID();
            connection.send(hello(staleEpoch, 0));
            assertThat(connection.receiveType("hello_ok")).isNotNull();
            var reset = connection.receiveType("sync_reset");
            assertThat(reset).isNotNull();
            assertThat(reset.path("epoch").stringValue()).isNotEqualTo(staleEpoch.toString());

            var capabilities = request(first, "/api/v1/capabilities", SESSION_A1);
            assertThat(capabilities.path("config_version").isMissingNode()).isFalse();
            assertThat(capabilities.path("enabled_capabilities").isMissingNode()).isTrue();
            assertThat(capabilities.path("limits").path("password_min_length").asInt()).isEqualTo(12);

            var head = request(first, "/api/v1/account/events/head", SESSION_A1);
            long headSequence = head.path("head_seq").asLong();
            String epoch = head.path("epoch").stringValue();
            long notification = createNotification(first, ACCOUNT_A);
            persist(first, context(ACCOUNT_A, SESSION_A1), List.of(
                    notificationCreated(ACCOUNT_A, notification, "cold:" + RUN_ID)));

            connection.send(Map.of("type", "resume", "epoch", epoch, "after_seq", headSequence));
            var frame = connection.receiveEvent();
            assertThat(frame.path("account_seq").asLong()).isEqualTo(headSequence + 1);
            assertThat(frame.path("data").path("notification_id").stringValue())
                    .isEqualTo(Long.toString(notification));
        }

        try (var stale = open(second, SESSION_A2)) {
            var head = request(second, "/api/v1/account/events/head", SESSION_A2);
            stale.send(hello(UUID.fromString(head.path("epoch").stringValue()), head.path("head_seq").asLong() + 100));
            assertThat(stale.receiveType("hello_ok")).isNotNull();
            assertThat(stale.receiveType("sync_reset")).isNotNull();
        }
    }

    @Test
    void normalEntryProjectsNotificationAndConversationEventsTogether() throws Exception {
        var conversation = SOURCES.conversation(ConversationKind.TRADE, ACCOUNT_A);
        long message = conversation.message(3, null);
        long notification = createNotification(first, ACCOUNT_A);

        try (var connection = open(first, SESSION_A1)) {
            helloAtHead(connection, first, ACCOUNT_A);
            persist(first, context(ACCOUNT_A, SESSION_A1), List.of(
                    messageCreated(ACCOUNT_A, conversation, message, "normal-message:" + RUN_ID),
                    notificationCreated(ACCOUNT_A, notification, "normal-notification:" + RUN_ID)));
            dispatch(first);

            var messageFrame = connection.receiveEvent();
            assertThat(messageFrame.path("event_type").stringValue()).isEqualTo("message_created");
            assertThat(messageFrame.path("data").path("conversation_kind").stringValue()).isEqualTo("trade");
            assertThat(messageFrame.path("data").path("message_id").stringValue()).isEqualTo(Long.toString(message));
            var notificationFrame = connection.receiveEvent();
            assertThat(notificationFrame.path("event_type").stringValue()).isEqualTo("notification_created");
            assertThat(notificationFrame.path("data").path("notification_id").stringValue())
                    .isEqualTo(Long.toString(notification));
        }
    }

    private static ConfigurableApplicationContext start() {
        var properties = new Properties();
        properties.putAll(environment);
        properties.setProperty("REDIS_NAMESPACE", namespace);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("EVENT_HEAD_POLL_SECONDS", "60");
        var application = new SpringApplication(BackendAppApplication.class, Fixtures.class,
                TradeLifecycleIT.Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("business-it", properties)));
        return application.run("--spring.profiles.active=infrastructure",
                "--server.port=0", "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
    }

    private static void close(ConfigurableApplicationContext context) {
        if (context != null) context.close();
    }

    private static Connection open(ConfigurableApplicationContext app, UUID session) throws Exception {
        int port = ((WebServerApplicationContext) app).getWebServer().getPort();
        return Connection.open(port, session);
    }

    private static JsonNode helloAtHead(Connection connection, ConfigurableApplicationContext app, long account)
            throws Exception {
        var head = app.getBean(UserEvents.class).head(account);
        connection.send(hello(head.epoch(), head.headSequence()));
        var frame = connection.receiveType("hello_ok");
        assertThat(frame).as("hello_ok").isNotNull();
        return frame;
    }

    private static Map<String, ?> hello(UUID epoch, long after) {
        return Map.of("type", "hello", "protocol_version", 1, "csrf_token", CSRF,
                "cursor", Map.of("epoch", epoch.toString(), "after_seq", after));
    }

    private static void persist(ConfigurableApplicationContext app, ExecutionContext context,
                                List<EventIntent> intents) {
        app.getBean(TransactionTemplate.class).executeWithoutResult(status ->
                app.getBean(UserEvents.class).persist(context, intents));
    }

    private static JsonNode createNotifications(ConfigurableApplicationContext app, String intentKey) {
        var notifications = app.getBean(NotificationApplication.class);
        var clock = app.getBeanProvider(Clock.class).getIfAvailable(Clock::systemUTC);
        var intent = new NotificationIntent(Set.of(ACCOUNT_A, ACCOUNT_B), null, "product_audit.passed",
                new ResourceRef("product_audit", 1001L), intentKey, "product_audit.decision", "1",
                Map.of("decision", "passed"), clock.instant());
        var result = app.getBean(WriteExecutor.class).run(context(ACCOUNT_A, SESSION_A1), "notification.create", intentKey,
                intent, new WriteExecutor.UseCase<NotificationIntent, Boolean>() {
                    @Override
                    public JsonNode digestInput(NotificationIntent request) {
                        return JSON.createObjectNode().put("intent_key", request.intentKey());
                    }

                    @Override
                    public LockPlan prepare(ExecutionContext context, NotificationIntent request) {
                        return EMPTY;
                    }

                    @Override
                    public Boolean qualify(ExecutionContext context, NotificationIntent request, LockPlan plan) {
                        return Boolean.TRUE;
                    }

                    @Override
                    public void requireReplayAccess(ExecutionContext context, Boolean qualified,
                                                    ResourceRef resource) {}

                    @Override
                    public WriteResult.Response<?> write(WriteTransaction transaction, NotificationIntent request,
                                                         Boolean qualified, LockPlan plan) {
                        var response = JSON.createObjectNode();
                        notifications.createNotifications(transaction, request).items().forEach(item ->
                                response.put(Long.toString(item.recipientAccountId()), item.notificationId()));
                        return new WriteResult.Response<>(201, response, request.source());
                    }
                });
        return result.data();
    }

    private static long createNotification(ConfigurableApplicationContext app, long account) {
        return app.getBean(JdbcClient.class).sql("""
                        INSERT INTO public.notification (recipient_account_id, intent_key, event_type,
                                source_type, source_id, template_key, template_version, display_params,
                                occurred_at, created_at)
                        VALUES (?, ?, 'product_audit.passed', 'product_audit', ?, 'product_audit.decision', '1',
                                '{"values":{}}'::jsonb, statement_timestamp() - interval '1 minute',
                                statement_timestamp() - interval '1 minute')
                        RETURNING notification_id
                        """)
                .param(account)
                .param("realtime:" + RUN_ID + ":" + UUID.randomUUID())
                .param(ThreadLocalRandom.current().nextLong(1L << 40, 1L << 50))
                .query(Long.class)
                .single();
    }

    private static void setNotificationReadAt(ConfigurableApplicationContext app, long notification, Instant readAt) {
        int updated = app.getBean(JdbcClient.class)
                .sql("UPDATE public.notification SET read_at = ? WHERE notification_id = ?")
                .param(Timestamp.from(readAt))
                .param(notification)
                .update();
        assertThat(updated).isEqualTo(1);
    }

    private static Instant storedNotificationReadAt(ConfigurableApplicationContext app, long notification) {
        return app.getBean(JdbcClient.class)
                .sql("SELECT read_at FROM public.notification WHERE notification_id = ?")
                .param(notification)
                .query(Timestamp.class)
                .single()
                .toInstant();
    }

    private static void dispatch(ConfigurableApplicationContext app) {
        assertThat(app.getBean(EventDispatch.class).publishDue()).isPositive();
    }

    private static ExecutionContext context(long account, UUID session) {
        return context(account, session, null);
    }

    private static ExecutionContext context(long account, UUID session, UUID origin) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(account), session, origin, 1L, "business-it");
    }

    private static EventIntent notificationCreated(long recipient, long notification, String key) {
        return new EventIntent(UUID.randomUUID(), recipient, "notification_created", 1,
                new ResourceRef("notification", notification), key, null, null);
    }

    private static EventIntent notificationRead(long recipient, long notification, String key) {
        return new EventIntent(UUID.randomUUID(), recipient, "notification_read", 1,
                new ResourceRef("notification", notification), key, null, null);
    }

    private static EventIntent messageCreated(long recipient, Controlled.Conversation conversation, long message, String key) {
        return new EventIntent(UUID.randomUUID(), recipient, "message_created", 1,
                new ResourceRef(conversation.kind.sourceType(), conversation.id), key,
                new ResourceRef(conversation.kind.wireName() + "_message", message), null);
    }

    private static JsonNode request(ConfigurableApplicationContext app, String path, UUID session)
            throws Exception {
        var response = HTTP.send(requestBuilder(app, path, session).GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as(path).isEqualTo(200);
        return JSON.readTree(response.body());
    }

    private static int requestStatus(ConfigurableApplicationContext app, String path, UUID session)
            throws Exception {
        return HTTP.send(requestBuilder(app, path, session).GET().build(),
                HttpResponse.BodyHandlers.ofString()).statusCode();
    }

    private static HttpRequest.Builder requestBuilder(ConfigurableApplicationContext app, String path, UUID session) {
        int port = ((WebServerApplicationContext) app).getWebServer().getPort();
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .timeout(Duration.ofSeconds(8));
        if (session != null) builder.header("Cookie", "it_session=" + session);
        return builder;
    }

    static final class Controlled {
        private final Map<UUID, SessionState> sessions = new ConcurrentHashMap<>();
        private final Map<ConversationKey, ConversationState> conversations = new ConcurrentHashMap<>();

        void addSession(UUID session, long account) {
            sessions.put(session, new SessionState(account, session));
        }

        void revoke(UUID session) {
            sessions.get(session).revoked = true;
        }

        Conversation conversation(ConversationKind kind, long account) {
            long id = ThreadLocalRandom.current().nextLong(1L << 40, 1L << 50);
            var conversation = new ConversationState(Set.of(account));
            conversations.put(new ConversationKey(kind, id), conversation);
            return new Conversation(kind, id, conversation);
        }

        void clear() {
            sessions.clear();
            conversations.clear();
        }

        private static long account(ExecutionContext context) {
            return Long.parseLong(context.actorId());
        }

        record ConversationKey(ConversationKind kind, long id) {}

        static final class Conversation {
            private final ConversationKind kind;
            private final long id;
            private final ConversationState state;

            private Conversation(ConversationKind kind, long id, ConversationState state) {
                this.kind = kind;
                this.id = id;
                this.state = state;
            }

            long message(long sequence, UUID businessEventId) {
                long message = ThreadLocalRandom.current().nextLong(1L << 40, 1L << 50);
                state.messages.put(message, new MessageState(sequence, businessEventId));
                return message;
            }

            void readable(boolean readable) {
                state.readable = readable;
            }
        }

        static final class SessionState {
            private final long account;
            private final UUID id;
            private volatile boolean revoked;

            private SessionState(long account, UUID id) {
                this.account = account;
                this.id = id;
            }
        }

        static final class ConversationState {
            private final Set<Long> participants;
            private final Map<Long, MessageState> messages = new ConcurrentHashMap<>();
            private volatile boolean readable = true;

            private ConversationState(Set<Long> participants) {
                this.participants = participants;
            }
        }

        record MessageState(long sequence, UUID businessEventId) {}
    }

    @TestConfiguration(proxyBeanMethods = false)
    public static class Fixtures {
        @Bean
        public RealtimeSessions realtimeSessions() {
            return new RealtimeSessions() {
                @Override
                public Optional<RealtimeAccess.Session> resolve(HttpServletRequest request) {
                    var cookies = request.getCookies();
                    if (cookies == null) return Optional.empty();
                    for (Cookie cookie : cookies) {
                        if (!"it_session".equals(cookie.getName())) continue;
                        var state = SOURCES.sessions.get(UUID.fromString(cookie.getValue()));
                        if (state == null || state.revoked) {
                            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "fixture");
                        }
                        return Optional.of(new RealtimeAccess.Session(state.account, state.id, 1L, "business-it"));
                    }
                    return Optional.empty();
                }

                @Override
                public void requireCurrent(RealtimeAccess.Session session) {
                    var state = SOURCES.sessions.get(session.id());
                    if (state == null || state.revoked) {
                        throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "fixture");
                    }
                }

                @Override
                public void requireCsrf(RealtimeAccess.Session session, String token) {
                    if (!CSRF.equals(token)) throw new BusinessError("CSRF_INVALID", 403, "fixture");
                }

                @Override
                public PublicAccountLimits publicLimits() {
                    return new PublicAccountLimits(12, 256, 64);
                }
            };
        }

        @Bean
        public RealtimeEventSources.Conversations conversations() {
            return new RealtimeEventSources.Conversations() {
                @Override
                public boolean canRead(ExecutionContext context, ConversationRef conversation) {
                    var state = SOURCES.conversations.get(
                            new Controlled.ConversationKey(conversation.kind(), conversation.id()));
                    return state != null && state.readable
                            && state.participants.contains(Controlled.account(context));
                }

                @Override
                public Optional<RealtimeEventSources.MessageHint> readMessage(ExecutionContext context,
                                                                              ConversationRef conversation,
                                                                              long messageId) {
                    if (!canRead(context, conversation)) return Optional.empty();
                    var state = SOURCES.conversations.get(
                            new Controlled.ConversationKey(conversation.kind(), conversation.id()));
                    var message = state.messages.get(messageId);
                    return message == null ? Optional.empty()
                            : Optional.of(new RealtimeEventSources.MessageHint(
                                    message.sequence(), message.businessEventId()));
                }
            };
        }
    }

    static final class Connection implements WebSocket.Listener, AutoCloseable {
        private final BlockingQueue<JsonNode> frames = new LinkedBlockingQueue<>();
        private final CompletableFuture<Integer> closeCode = new CompletableFuture<>();
        private final Queue<JsonNode> pending = new ArrayDeque<>();
        private final StringBuilder buffer = new StringBuilder();
        private WebSocket socket;

        static Connection open(int port, UUID session) {
            var connection = new Connection();
            connection.socket = HTTP.newWebSocketBuilder().connectTimeout(Duration.ofSeconds(5))
                    .header("Origin", ORIGIN).header("Cookie", "it_session=" + session)
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
                    source.sendText(JSON.writeValueAsString(Map.of("type", "pong",
                            "nonce", frame.path("nonce").stringValue())), true);
                } else {
                    frames.add(frame);
                }
            }
            source.request(1);
            return null;
        }

        @Override
        public CompletionStage<?> onClose(WebSocket source, int statusCode, String reason) {
            closeCode.complete(statusCode);
            return null;
        }

        void send(Map<String, ?> frame) {
            socket.sendText(JSON.writeValueAsString(frame), true).orTimeout(5, TimeUnit.SECONDS).join();
        }

        JsonNode receiveType(String type) throws InterruptedException {
            return receive(frame -> type.equals(frame.path("type").stringValue()));
        }

        JsonNode receiveEvent() throws InterruptedException {
            return receive(frame -> "event".equals(frame.path("type").stringValue())
                    || "cursor_advance".equals(frame.path("type").stringValue()));
        }

        boolean noFrame(Duration duration) throws InterruptedException {
            if (!pending.isEmpty()) return false;
            return frames.poll(duration.toMillis(), TimeUnit.MILLISECONDS) == null;
        }

        private JsonNode receive(java.util.function.Predicate<JsonNode> predicate) throws InterruptedException {
            for (var iterator = pending.iterator(); iterator.hasNext(); ) {
                var frame = iterator.next();
                if (predicate.test(frame)) {
                    iterator.remove();
                    return frame;
                }
            }
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
            while (System.nanoTime() < deadline) {
                var frame = frames.poll(deadline - System.nanoTime(), TimeUnit.NANOSECONDS);
                if (frame == null) return null;
                if (predicate.test(frame)) return frame;
                pending.add(frame);
            }
            return null;
        }

        @Override
        public void close() {
            try {
                socket.sendClose(WebSocket.NORMAL_CLOSURE, "").orTimeout(2, TimeUnit.SECONDS).join();
            } catch (RuntimeException ignored) {
                // The server may already have closed a revoked Session.
            } finally {
                socket.abort();
            }
        }
    }
}
