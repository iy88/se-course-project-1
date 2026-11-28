package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationPage;
import io.github.iy88.project1.notification.application.NotificationQueries;
import io.github.iy88.project1.notification.application.NotificationQuery;
import io.github.iy88.project1.notification.persistence.NotificationStore;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Notification persistence against the real PostgreSQL schema.
 *
 * The module's unit tests cover the rules with an in-memory store; this test proves
 * the {@code notification} table, its unique scope, the first-read write and the
 * paging predicates behave as the module expects under a real database, with the
 * delivery intents persisted in the same transaction.
 */
class NotificationPersistenceIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final UUID SESSION_ID = UUID.randomUUID();
    private static final long SELLER = ThreadLocalRandom.current().nextLong(1L << 42, 1L << 52);
    private static final long SECOND_RECIPIENT = SELLER + 1;
    private static final long OTHER_ACCOUNT = SELLER + 2;
    /** Dedicated recipient for the paging test so other cases cannot change its totals. */
    private static final long PAGE_RECIPIENT = SELLER + 3;
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final LockPlan EMPTY = new LockPlan(Map.of(), Set.of());

    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static WriteExecutor writes;
    private static NotificationApplication notifications;
    private static NotificationQueries queries;
    private static NotificationStore store;

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
        properties.setProperty("REDIS_NAMESPACE", baseNamespace + ":notification-it:" + RUN_ID);
        properties.setProperty("ALLOWED_ORIGINS", "http://127.0.0.1:3000");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        var application = new SpringApplication(BackendAppApplication.class, InfrastructureIT.Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("integration", properties)));
        app = application.run("--spring.profiles.active=infrastructure",
                "--server.port=0", "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        writes = app.getBean(WriteExecutor.class);
        notifications = app.getBean(NotificationApplication.class);
        queries = app.getBean(NotificationQueries.class);
        store = app.getBean(NotificationStore.class);
    }

    @AfterAll
    static void cleanUp() {
        if (app == null) return;
        try (var _ = app) {
            for (long account : List.of(SELLER, SECOND_RECIPIENT, OTHER_ACCOUNT, PAGE_RECIPIENT)) {
                db.sql("DELETE FROM notification WHERE recipient_account_id = ?").param(account).update();
                db.sql("DELETE FROM user_event WHERE recipient_account_id = ?").param(account).update();
                db.sql("DELETE FROM account_event_head WHERE account_id = ?").param(account).update();
                db.sql("DELETE FROM operation_record WHERE actor_kind = 'account' AND actor_id = ?")
                        .param(Long.toString(account)).update();
            }
        }
    }

    @Test
    void writesOneCreatedEventPerRecipientWithThatNotificationReference() {
        String intentKey = key("create");
        var intent = intent(intentKey, "product_audit.passed", SELLER, SECOND_RECIPIENT);

        var created = create("notification.create", intentKey, intent);
        assertThat(created.replayed()).isFalse();
        assertThat(notificationRows(intentKey)).isEqualTo(2);

        // Two outbox rows, each addressed to its own recipient and referencing that
        // recipient's notification; no row is duplicated or cross-referenced.
        assertThat(eventRows(intentKey)).isEqualTo(2);
        assertThat(createdEventsFor(intentKey, SELLER)).isEqualTo(1);
        assertThat(createdEventsFor(intentKey, SECOND_RECIPIENT)).isEqualTo(1);
        assertThat(mismatchedCreatedEvents(intentKey)).isZero();
        assertThat(duplicateCreatedEvents(intentKey)).isZero();

        var replay = create("notification.create", intentKey, intent);
        assertThat(replay.replayed()).isTrue();
        assertThat(replay.operationId()).isEqualTo(created.operationId());
        assertThat(notificationRows(intentKey)).isEqualTo(2);
        assertThat(eventRows(intentKey)).isEqualTo(2);
        assertThat(duplicateCreatedEvents(intentKey)).isZero();
    }

    @Test
    void registersACreatedEventOnlyForTheRecipientThatWasNotStoredYet() {
        String intentKey = key("partial");

        // First call stores the seller only, so only the seller gets an event.
        create("notification.create", intentKey, intent(intentKey, "product_audit.passed", SELLER));
        assertThat(createdEventsFor(intentKey, SELLER)).isEqualTo(1);
        assertThat(createdEventsFor(intentKey, SECOND_RECIPIENT)).isZero();

        // The second call is a different action (fresh idempotency key, same intent
        // key) that adds the missing recipient; the stored one is left alone.
        create("notification.create", key("partial-second"),
                intent(intentKey, "product_audit.passed", SELLER, SECOND_RECIPIENT));
        assertThat(notificationRows(intentKey)).isEqualTo(2);
        assertThat(createdEventsFor(intentKey, SELLER)).isEqualTo(1);
        assertThat(createdEventsFor(intentKey, SECOND_RECIPIENT)).isEqualTo(1);
        assertThat(mismatchedCreatedEvents(intentKey)).isZero();
        assertThat(duplicateCreatedEvents(intentKey)).isZero();
    }

    @Test
    void rejectsTheSameIntentKeyWithDifferentContent() {
        String intentKey = key("conflict");
        create("notification.create", intentKey, intent(intentKey, "product_audit.passed", SELLER));

        // Same recipient and intent key, different event type, template and reason.
        var conflicting = new NotificationIntent(Set.of(SELLER), null, "product_audit.rejected",
                new ResourceRef("product_audit", 1001L), intentKey, "product_audit.decision", "2",
                Map.of("reason", "改判"), Instant.parse("2026-11-22T10:05:00Z"));

        // A fresh idempotency key models a different action that reuses the intent
        // key; the retry path with the same key is covered by the replay test.
        assertThatThrownBy(() -> create("notification.create", key("conflict-second"), conflicting))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code())
                        .isEqualTo("NOTIFICATION_INTENT_CONFLICT"));
        assertThat(notificationRows(intentKey)).isEqualTo(1);
    }

    @Test
    void rejectsTheSameIntentKeyWithDifferentTemplateParameters() {
        String intentKey = key("params");
        create("notification.create", intentKey, intent(intentKey, "product_audit.passed", SELLER));

        // Same event type, source and template; only a template parameter differs.
        var conflicting = new NotificationIntent(Set.of(SELLER), null, "product_audit.passed",
                new ResourceRef("product_audit", 1001L), intentKey, "notification.template", "1",
                Map.of("summary", "另一条说明"), Instant.parse("2026-11-22T10:00:00Z"));

        assertThatThrownBy(() -> create("notification.create", key("params-second"), conflicting))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code())
                        .isEqualTo("NOTIFICATION_INTENT_CONFLICT"));
        assertThat(notificationRows(intentKey)).isEqualTo(1);
    }

    @Test
    void enforcesTheRecipientIntentScopeInTheDatabase() {
        String intentKey = key("unique");
        create("notification.create", intentKey, intent(intentKey, "product_audit.passed", SELLER));

        // Bypass the module: the database itself must reject a second row for the scope.
        assertThatThrownBy(() -> db.sql("""
                        INSERT INTO notification(recipient_account_id, intent_key, event_type, source_type, source_id,
                            template_key, template_version, display_params, occurred_at, created_at)
                        VALUES (:recipient, :intent, 'product_audit.passed', 'product_audit', 1001,
                            'product_audit.decision', '1', '{}'::jsonb, statement_timestamp(), statement_timestamp())
                        """)
                .param("recipient", SELLER).param("intent", intentKey).update())
                .isInstanceOf(DataIntegrityViolationException.class);
        assertThat(notificationRows(intentKey)).isEqualTo(1);
    }

    @Test
    void recordsTheFirstReadOnceAndEmitsOneEvent() {
        String intentKey = key("read");
        create("notification.create", intentKey, intent(intentKey, "product_audit.rejected", SELLER));
        long notificationId = store.find(SELLER, intentKey).orElseThrow().notificationId();

        markRead(SELLER, notificationId, key("read-first"));
        var afterFirst = store.findForRecipient(notificationId, SELLER).orElseThrow().readAt();
        assertThat(afterFirst).isNotNull();

        // A second, differently keyed read must not move the instant or add an event.
        markRead(SELLER, notificationId, key("read-second"));
        var afterSecond = store.findForRecipient(notificationId, SELLER).orElseThrow().readAt();
        assertThat(afterSecond).isEqualTo(afterFirst);
        assertThat(readEventRows(notificationId)).isEqualTo(1);
    }

    @Test
    void filtersBeforePagingAndCountsTheWholeUnreadTotal() {
        String base = key("page");
        String[] eventTypes = {"product_audit.passed", "case.inquiry_created", "product_audit.passed"};
        for (int index = 0; index < eventTypes.length; index++) {
            String intentKey = base + ":" + index;
            create("notification.create", intentKey,
                    intent(intentKey, eventTypes[index], PAGE_RECIPIENT));
        }
        long newest = store.find(PAGE_RECIPIENT, base + ":2").orElseThrow().notificationId();
        markRead(PAGE_RECIPIENT, newest, key("page-read"));

        var context = context(PAGE_RECIPIENT);
        NotificationPage unread = queries.list(context,
                new NotificationQuery(1, 20, NotificationQuery.ReadFilter.UNREAD, null));
        NotificationPage all = queries.list(context,
                new NotificationQuery(1, 20, NotificationQuery.ReadFilter.ALL, null));
        NotificationPage byEvent = queries.list(context,
                new NotificationQuery(1, 1, NotificationQuery.ReadFilter.ALL, "case.inquiry_created"));

        assertThat(all.total()).isEqualTo(3);
        assertThat(all.unreadCount()).isEqualTo(2);
        assertThat(unread.total()).isEqualTo(2);
        assertThat(unread.unreadCount()).isEqualTo(all.unreadCount());
        assertThat(byEvent.total()).isEqualTo(1);
        assertThat(byEvent.items()).hasSize(1);
        assertThat(byEvent.items().get(0).eventType()).isEqualTo("case.inquiry_created");
        assertThat(unread.items()).extracting(entry -> entry.notificationId()).doesNotContain(newest);
    }

    @Test
    void hidesAnotherAccountsNotification() {
        String intentKey = key("hidden");
        create("notification.create", intentKey, intent(intentKey, "case.trade_frozen", SELLER));
        long notificationId = store.find(SELLER, intentKey).orElseThrow().notificationId();

        assertThatThrownBy(() -> queries.get(context(OTHER_ACCOUNT), notificationId))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code())
                        .isEqualTo("RESOURCE_NOT_VISIBLE"));
        assertThatThrownBy(() -> markRead(OTHER_ACCOUNT, notificationId, key("hidden-read")))
                .isInstanceOf(BusinessError.class)
                .satisfies(error -> assertThat(((BusinessError) error).code())
                        .isEqualTo("RESOURCE_NOT_VISIBLE"));
    }

    /* ------------------------------------------------------------------ helpers */

    @FunctionalInterface
    private interface IntentBody {
        WriteResult.Response<?> apply(WriteTransaction transaction, NotificationIntent intent);
    }

    private static WriteResult<JsonNode> runWrite(String operation, String idempotencyKey,
                                                  NotificationIntent intent, IntentBody body) {
        return writes.run(context(SELLER), operation, idempotencyKey, intent,
                new WriteExecutor.UseCase<NotificationIntent, Boolean>() {
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
                        return body.apply(transaction, request);
                    }
                });
    }

    private static WriteResult<JsonNode> create(String operation, String idempotencyKey,
                                                NotificationIntent intent) {
        return runWrite(operation, idempotencyKey, intent, (transaction, request) -> {
            var batch = notifications.createNotifications(transaction, request);
            return new WriteResult.Response<>(201, Map.of("notifications", batch.items().size()),
                    request.source());
        });
    }

    private static WriteResult<JsonNode> markRead(long accountId, long notificationId,
                                                  String idempotencyKey) {
        return writes.run(context(accountId), "notification.mark_read", idempotencyKey, notificationId,
                new WriteExecutor.UseCase<Long, Boolean>() {
                    @Override
                    public JsonNode digestInput(Long request) {
                        return JSON.createObjectNode().put("notification_id", Long.toString(request));
                    }

                    @Override
                    public LockPlan prepare(ExecutionContext context, Long request) {
                        return new LockPlan(Map.of(), Set.of(
                                new LockPlan.Key(LockPlan.Domain.NOTIFICATION, List.of(request))));
                    }

                    @Override
                    public Boolean qualify(ExecutionContext context, Long request, LockPlan plan) {
                        return Boolean.TRUE;
                    }

                    @Override
                    public void requireReplayAccess(ExecutionContext context, Boolean qualified,
                                                    ResourceRef resource) {}

                    @Override
                    public WriteResult.Response<?> write(WriteTransaction transaction, Long request,
                                                         Boolean qualified, LockPlan plan) {
                        var item = notifications.markRead(transaction, accountId, request);
                        return new WriteResult.Response<>(200,
                                Map.of("notification_id", Long.toString(item.notificationId())),
                                new ResourceRef("notification", request));
                    }
                });
    }

    private static NotificationIntent intent(String intentKey, String eventType, long... recipients) {
        var ids = new TreeSet<Long>();
        for (long recipient : recipients) ids.add(recipient);
        var source = eventType.startsWith("case.")
                ? new ResourceRef("case", 2001L)
                : new ResourceRef("product_audit", 1001L);
        return new NotificationIntent(ids, null, eventType, source, intentKey, "notification.template", "1",
                Map.of("summary", "集成测试通知"), Instant.parse("2026-11-22T10:00:00Z"));
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), SESSION_ID, null, 1L, "integration");
    }

    private static String key(String label) {
        return "it:" + RUN_ID + ":" + label;
    }

    private static long notificationRows(String intentKey) {
        return db.sql("SELECT count(*) FROM notification WHERE intent_key = ?")
                .param(intentKey).query(Long.class).single();
    }

    private static long eventRows(String intentKey) {
        return db.sql("SELECT count(*) FROM user_event WHERE intent_key = ?")
                .param(intentKey).query(Long.class).single();
    }

    private static long readEventRows(long notificationId) {
        return db.sql("SELECT count(*) FROM user_event WHERE event_type = 'notification_read' AND payload_id = ?")
                .param(notificationId).query(Long.class).single();
    }

    /**
     * Counts {@code notification_created} rows for one recipient in the intent scope.
     */
    private static long createdEventsFor(String intentKey, long recipient) {
        return db.sql("""
                SELECT count(*) FROM user_event
                WHERE intent_key = ? AND recipient_account_id = ? AND event_type = 'notification_created'
                """)
                .param(intentKey).param(recipient).query(Long.class).single();
    }

    /**
     * Counts created events whose notification reference or recipient does not match
     * the stored notification. A non-zero result means the realtime projection would
     * announce the wrong row to the wrong account.
     */
    private static long mismatchedCreatedEvents(String intentKey) {
        return db.sql("""
                SELECT count(*) FROM user_event e
                LEFT JOIN notification n ON n.notification_id = e.payload_id
                WHERE e.intent_key = ? AND e.event_type = 'notification_created'
                  AND (n.notification_id IS NULL
                       OR n.recipient_account_id <> e.recipient_account_id
                       OR n.intent_key <> e.intent_key)
                """)
                .param(intentKey).query(Long.class).single();
    }

    /** Counts recipients that received more than one created event for the same intent. */
    private static long duplicateCreatedEvents(String intentKey) {
        return db.sql("""
                SELECT count(*) FROM (
                    SELECT recipient_account_id FROM user_event
                    WHERE intent_key = ? AND event_type = 'notification_created'
                    GROUP BY recipient_account_id
                    HAVING count(*) > 1
                ) duplicated
                """)
                .param(intentKey).query(Long.class).single();
    }
}
