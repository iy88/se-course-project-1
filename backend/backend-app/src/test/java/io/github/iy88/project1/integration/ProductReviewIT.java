package io.github.iy88.project1.integration;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.api.CsrfGuard;
import io.github.iy88.project1.api.trade.TradeActorResolver;
import io.github.iy88.project1.casemanagement.application.ProductReviewCases;
import io.github.iy88.project1.casemanagement.application.ReviewAction;
import io.github.iy88.project1.casemanagement.application.ReviewApplication;
import io.github.iy88.project1.casemanagement.application.ReviewDecisionInput;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.application.TradePorts;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Real PostgreSQL/Spring transaction integration for product-review claim and decision. The case
 * and notification tables use the production schema and adapters. Product, category and account
 * data use fixtures.
 */
class ProductReviewIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final String FIXTURE_SCHEMA = "review_it_" + RUN_ID.toString().replace("-", "");
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String CSRF = "fixture-csrf";
    private static final long MANAGER_1 = ThreadLocalRandom.current().nextLong(1L << 42, 1L << 52);
    private static final long MANAGER_2 = MANAGER_1 + 1;
    private static final long NON_MANAGER = MANAGER_1 + 2;
    private static final long SELLER = MANAGER_1 + 3;
    private static final UUID MANAGER_1_SESSION = UUID.randomUUID();
    private static final UUID MANAGER_2_SESSION = UUID.randomUUID();
    private static final UUID NON_MANAGER_SESSION = UUID.randomUUID();
    private static final UUID SELLER_SESSION = UUID.randomUUID();
    private static final long PRODUCT = 21_000_000_001L;
    private static final long CATEGORY = 21_000_000_002L;
    private static final long APPLICATION = 21_000_000_003L;
    private static final long BANNED_ITEM = 21_000_000_004L;
    private static final Instant NOW = Instant.parse("2026-01-01T00:00:00Z");
    private static final AtomicLong AUDITS = new AtomicLong(31_000_000_001L);

    private static JdbcClient fixtureOwner;
    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static JsonMapper json;
    private static ProductReviewFixturePort port;
    private static ReviewApplication reviews;
    private static ReviewCaseStore cases;
    private static WriteExecutor writes;
    private static MockMvc mvc;
    private static final Set<Long> TRACKED_CASES = ConcurrentHashMap.newKeySet();
    private static final Map<Long, Long> CASE_BY_AUDIT = new ConcurrentHashMap<>();

    @BeforeAll
    static void startApplication() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        String namespace = properties.getProperty("REDIS_NAMESPACE");
        if (namespace == null || namespace.isBlank()) {
            throw new IllegalArgumentException("REDIS_NAMESPACE is required");
        }
        properties.setProperty("REDIS_NAMESPACE", namespace + ":review:" + RUN_ID);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("CONFIG_VERSION", "review-it");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        createFixtures(properties);
        properties.setProperty("spring.datasource.hikari.connection-init-sql",
                "SET search_path TO " + FIXTURE_SCHEMA + ", public");
        properties.setProperty("spring.jpa.properties.hibernate.default_schema", "public");

        var application = new SpringApplication(BackendAppApplication.class, Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("review-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        json = app.getBean(JsonMapper.class);
        port = app.getBean(ProductReviewFixturePort.class);
        reviews = app.getBean(ReviewApplication.class);
        cases = app.getBean(ReviewCaseStore.class);
        writes = app.getBean(WriteExecutor.class);
        mvc = MockMvcBuilders.webAppContextSetup((WebApplicationContext) app)
                .addFilters(app.getBean(ApiRequestContext.class))
                .build();
    }

    @AfterAll
    static void stopApplication() {
        try {
            if (app != null) {
                try (var context = app) {
                    cleanupCases();
                }
            }
        } finally {
            if (fixtureOwner != null) {
                fixtureOwner.sql("DROP SCHEMA IF EXISTS " + FIXTURE_SCHEMA + " CASCADE").update();
            }
        }
    }

    @BeforeEach
    void resetFixtures() {
        cleanupCases();
        db.sql("""
                TRUNCATE review_category_application_fixture, review_audit_fixture,
                    review_product_category_fixture, review_product_image_fixture, review_product_fixture,
                    review_category_fixture, review_banned_item_fixture, review_manager_fixture,
                    review_session_fixture, review_seller_fixture CASCADE
                """).update();
        cleanupInfrastructure();
        port.trace().clear();
        CASE_BY_AUDIT.clear();

        db.sql("INSERT INTO review_seller_fixture (account_id, display_name) VALUES (?, ?)")
                .param(SELLER).param("Seller").update();
        insertSession(MANAGER_1, MANAGER_1_SESSION);
        insertSession(MANAGER_2, MANAGER_2_SESSION);
        insertSession(NON_MANAGER, NON_MANAGER_SESSION);
        db.sql("INSERT INTO review_manager_fixture (account_id) VALUES (?), (?)")
                .param(MANAGER_1).param(MANAGER_2).update();
        db.sql("INSERT INTO review_category_fixture (category_id, main_name, selectable) VALUES (?, ?, TRUE)")
                .param(CATEGORY).param("Existing").update();
        db.sql("INSERT INTO review_banned_item_fixture (item_id, group_name, content, active) VALUES (?, ?, ?, TRUE)")
                .param(BANNED_ITEM).param("medicine_device").param("restricted item").update();
        db.sql("""
                INSERT INTO review_product_fixture
                    (product_id, seller_account_id, title, description, price_cents, content_version, lifecycle_state)
                VALUES (?, ?, 'v1', 'description', 1000, 1, 'pending_review')
                """).param(PRODUCT).param(SELLER).update();
        db.sql("INSERT INTO review_product_image_fixture (product_id, file_id) VALUES (?, 1), (?, 2)")
                .param(PRODUCT).param(PRODUCT).update();
        db.sql("INSERT INTO review_product_category_fixture (product_id, category_id) VALUES (?, ?)")
                .param(PRODUCT).param(CATEGORY).update();
    }

    @AfterEach
    void cleanUp() {
        cleanupCases();
        cleanupInfrastructure();
    }

    @Test
    void rejectionThenResubmissionCreatesANewCaseAndApprovalPublishesTheProduct() {
        long firstAudit = AUDITS.getAndIncrement();
        long firstCase = submit(firstAudit, NOW, "v1", 1);
        assertThat(publicVisible()).isZero();

        var claimed = claim(MANAGER_1, MANAGER_1_SESSION, firstCase, "claim-first");
        assertThat(claimed.data().path("case_status").stringValue()).isEqualTo("claimed");
        assertThat(claimed.data().path("already_claimed").booleanValue()).isFalse();

        decide(MANAGER_1, MANAGER_1_SESSION, firstAudit, ReviewAction.REJECT, "prohibited", null, null,
                "decide-reject");
        assertThat(auditStatus(firstAudit)).isEqualTo("rejected");
        assertThat(productState()).isEqualTo("review_rejected");
        assertThat(publicVisible()).isZero();
        assertThat(sellerNotificationCount()).isEqualTo(1);
        var rejection = notification(firstAudit);
        assertThat(rejection.recipientAccountId()).isEqualTo(SELLER);
        assertThat(rejection.eventType()).isEqualTo("product_audit.rejected");
        assertThat(rejection.sourceType()).isEqualTo("product_audit");
        assertThat(rejection.sourceId()).isEqualTo(firstAudit);
        assertThat(rejection.intentKey()).isEqualTo(notificationIntentKey(firstAudit));
        assertThat(rejection.decision()).isEqualTo("rejected");
        assertThat(rejection.reason()).isEqualTo("prohibited");
        assertThat(createdNotificationEvents(firstAudit, rejection.notificationId())).isEqualTo(1);
        assertThat(sellerCreatedNotificationEvents()).isEqualTo(1);

        long secondAudit = AUDITS.getAndIncrement();
        long secondCase = submit(secondAudit, NOW.plusSeconds(60), "v2", 2);
        assertThat(secondCase).isNotEqualTo(firstCase);
        assertThat(caseActionCount(secondCase, "claim")).isZero();
        assertThatThrownBy(() -> claim(MANAGER_2, MANAGER_2_SESSION, firstCase, "claim-old"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("REVIEW_NOT_PENDING"));

        claim(MANAGER_2, MANAGER_2_SESSION, secondCase, "claim-second");
        decide(MANAGER_2, MANAGER_2_SESSION, secondAudit, ReviewAction.APPROVE, null, null, null,
                "decide-approve");
        assertThat(auditStatus(secondAudit)).isEqualTo("passed");
        assertThat(productState()).isEqualTo("public");
        assertThat(publicVisible()).isEqualTo(1);
        assertThat(sellerNotificationCount()).isEqualTo(2);
        var approval = notification(secondAudit);
        assertThat(approval.recipientAccountId()).isEqualTo(SELLER);
        assertThat(approval.eventType()).isEqualTo("product_audit.passed");
        assertThat(approval.sourceType()).isEqualTo("product_audit");
        assertThat(approval.sourceId()).isEqualTo(secondAudit);
        assertThat(approval.intentKey()).isEqualTo(notificationIntentKey(secondAudit));
        assertThat(approval.decision()).isEqualTo("passed");
        assertThat(approval.reason()).isNull();
        assertThat(createdNotificationEvents(secondAudit, approval.notificationId())).isEqualTo(1);
        assertThat(sellerCreatedNotificationEvents()).isEqualTo(2);
        assertThat(caseActionCount(secondCase, "decide")).isEqualTo(1);
    }

    @Test
    void sameKeyReplayAndAnotherKeyRetryDoNotDuplicateClaimOrDecisionFacts() {
        long auditId = AUDITS.getAndIncrement();
        long caseId = submit(auditId, NOW, "v1", 1);

        var claim = claim(MANAGER_1, MANAGER_1_SESSION, caseId, "claim-replay");
        var claimReplay = claim(MANAGER_1, MANAGER_1_SESSION, caseId, "claim-replay");
        assertThat(claimReplay.replayed()).isTrue();
        assertThat(claimReplay.data()).isEqualTo(claim.data());
        var claimAgain = claim(MANAGER_1, MANAGER_1_SESSION, caseId, "claim-new-key");
        assertThat(claimAgain.replayed()).isFalse();
        assertThat(claimAgain.data().path("already_claimed").booleanValue()).isTrue();
        assertThat(claimAgain.data().path("claimed_at").stringValue())
                .isEqualTo(claim.data().path("claimed_at").stringValue());
        assertThat(caseActionCount(caseId, "claim")).isEqualTo(1);
        assertThat(caseAuditCount(caseId)).isEqualTo(1);

        var decision = decide(MANAGER_1, MANAGER_1_SESSION, auditId, ReviewAction.APPROVE, null, null, null,
                "decide-replay");
        var decisionNotification = notification(auditId);
        assertThat(createdNotificationEvents(auditId, decisionNotification.notificationId())).isEqualTo(1);
        var decisionReplay = decide(MANAGER_1, MANAGER_1_SESSION, auditId, ReviewAction.APPROVE, null, null, null,
                "decide-replay");
        assertThat(decisionReplay.replayed()).isTrue();
        assertThat(decisionReplay.data()).isEqualTo(decision.data());
        assertThatThrownBy(() -> decide(MANAGER_1, MANAGER_1_SESSION, auditId, ReviewAction.APPROVE, null, null,
                null, "decide-new-key"))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("REVIEW_NOT_PENDING"));
        assertThat(sellerNotificationCount()).isEqualTo(1);
        assertThat(sellerCreatedNotificationEvents()).isEqualTo(1);
        var replayNotification = notification(auditId);
        assertThat(replayNotification.eventType()).isEqualTo("product_audit.passed");
        assertThat(replayNotification.sourceType()).isEqualTo("product_audit");
        assertThat(replayNotification.sourceId()).isEqualTo(auditId);
        assertThat(replayNotification.intentKey()).isEqualTo(notificationIntentKey(auditId));
        assertThat(replayNotification.reason()).isNull();
        assertThat(createdNotificationEvents(auditId, replayNotification.notificationId())).isEqualTo(1);
        assertThat(caseActionCount(caseId, "decide")).isEqualTo(1);
        assertThat(caseAuditCount(caseId)).isEqualTo(2);
    }

    @Test
    void competingManagersAtTheSameTimeProduceOneClaim() throws Exception {
        long auditId = AUDITS.getAndIncrement();
        long caseId = submit(auditId, NOW, "v1", 1);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var ready = new CountDownLatch(2);
            var start = new CountDownLatch(1);
            var first = executor.submit(() -> claimOrError(MANAGER_1, MANAGER_1_SESSION, caseId, "race-1",
                    ready, start));
            var second = executor.submit(() -> claimOrError(MANAGER_2, MANAGER_2_SESSION, caseId, "race-2",
                    ready, start));
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            var outcomes = List.of(first.get(15, TimeUnit.SECONDS), second.get(15, TimeUnit.SECONDS));
            assertThat(outcomes).hasSize(2);
            assertThat(outcomes.stream().filter(item -> item instanceof WriteResult)).hasSize(1);
            var rejection = outcomes.stream().filter(item -> item instanceof BusinessError)
                    .map(item -> (BusinessError) item).findFirst().orElseThrow();
            assertThat(rejection.code()).isEqualTo("CASE_ALREADY_CLAIMED");
            assertThat(caseActionCount(caseId, "claim")).isEqualTo(1);
            assertThat(caseAuditCount(caseId)).isEqualTo(1);
            assertThat(claimedManager(caseId)).isIn(MANAGER_1, MANAGER_2);
        }
    }

    @Test
    void aClaimedReviewCannotBeWithdrawn() {
        long auditId = AUDITS.getAndIncrement();
        long caseId = submit(auditId, NOW, "v1", 1);
        claim(MANAGER_1, MANAGER_1_SESSION, caseId, "claim-withdraw");

        assertThatThrownBy(() -> withdraw(caseId, "withdraw-claimed"))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("REVIEW_ALREADY_CLAIMED");
                    assertThat(error.status()).isEqualTo(409);
                });
        assertThat(claimedManager(caseId)).isEqualTo(MANAGER_1);
        assertThat(auditStatus(auditId)).isEqualTo("pending");
        assertThat(productState()).isEqualTo("pending_review");
    }

    @Test
    void notificationConflictRollsBackTheProductCategoryCaseActionAndIdempotency() {
        long auditId = AUDITS.getAndIncrement();
        long caseId = submit(auditId, NOW, "v1", 1);
        db.sql("""
                INSERT INTO review_category_application_fixture
                    (application_id, audit_id, proposed_name, status)
                VALUES (?, ?, 'New category', 'pending')
                """).param(APPLICATION).param(auditId).update();
        claim(MANAGER_1, MANAGER_1_SESSION, caseId, "claim-rollback");

        // Same seller and intent key as the decision, but different event content forces a conflict.
        long conflictingNotificationId = insertConflictingNotification(auditId);
        String conflictingBefore = notificationRowAsJson(conflictingNotificationId);

        String key = "decide-rollback";
        var failure = org.assertj.core.api.Assertions.catchThrowableOfType(
                () -> decide(MANAGER_1, MANAGER_1_SESSION, auditId, ReviewAction.APPROVE, null,
                        ReviewAction.APPROVE, "new category accepted", key),
                BusinessError.class);
        assertThat(failure).isNotNull();
        assertThat(failure.code()).isEqualTo("NOTIFICATION_INTENT_CONFLICT");
        assertThat(failure.status()).isEqualTo(409);
        assertThat(failure.operationId()).isNotNull();

        assertThat(auditStatus(auditId)).isEqualTo("pending");
        assertThat(auditReviewedVersion(auditId)).isNull();
        assertThat(productState()).isEqualTo("pending_review");
        assertThat(publicVisible()).isZero();
        assertThat(categoryApplicationStatus(auditId)).isEqualTo("pending");
        assertThat(db.sql("SELECT count(*) FROM review_category_fixture WHERE main_name = 'New category'")
                .query(Long.class).single()).isZero();
        assertThat(caseActionCount(caseId, "decide")).isZero();
        assertThat(operationCount(key)).isZero();
        assertThat(auditCount(failure.operationId())).isZero();
        assertThat(sellerNotificationCount()).isEqualTo(1);
        assertThat(sellerCreatedNotificationEvents()).isZero();
        assertThat(notificationRowAsJson(conflictingNotificationId)).isEqualTo(conflictingBefore);

        // Remove only the conflict seed; the retry must then commit through the real adapter.
        db.sql("DELETE FROM notification WHERE notification_id = ?")
                .param(conflictingNotificationId).update();
        assertThat(sellerNotificationCount()).isZero();
        assertThat(sellerCreatedNotificationEvents()).isZero();

        var recovered = decide(MANAGER_1, MANAGER_1_SESSION, auditId, ReviewAction.APPROVE, null,
                ReviewAction.APPROVE, "new category accepted", key);
        assertThat(recovered.replayed()).isFalse();
        assertThat(recovered.data().path("reviewed_content_version").intValue()).isEqualTo(1);
        assertThat(recovered.data().path("product").path("content_version").intValue()).isEqualTo(2);
        assertThat(auditStatus(auditId)).isEqualTo("passed");
        assertThat(productState()).isEqualTo("public");
        assertThat(categoryApplicationStatus(auditId)).isEqualTo("approved");
        assertThat(caseActionCount(caseId, "decide")).isEqualTo(1);
        assertThat(sellerNotificationCount()).isEqualTo(1);
        assertThat(sellerCreatedNotificationEvents()).isEqualTo(1);
        var recoveredNotification = notification(auditId);
        assertThat(recoveredNotification.eventType()).isEqualTo("product_audit.passed");
        assertThat(recoveredNotification.sourceType()).isEqualTo("product_audit");
        assertThat(recoveredNotification.sourceId()).isEqualTo(auditId);
        assertThat(recoveredNotification.intentKey()).isEqualTo(notificationIntentKey(auditId));
        assertThat(recoveredNotification.reason()).isNull();
        assertThat(createdNotificationEvents(auditId, recoveredNotification.notificationId())).isEqualTo(1);
    }

    @Test
    void httpEndpointsApplyTrustedIdentityOwnershipQueueFiltersAndStrictResponses() throws Exception {
        long firstAudit = AUDITS.getAndIncrement();
        long firstCase = submit(firstAudit, NOW, "v1", 1);
        long secondAudit = AUDITS.getAndIncrement();
        long secondCase = submit(secondAudit, NOW.plusSeconds(30), "v2", 2);

        mvc.perform(get(path("/management/todos")).header("Origin", ORIGIN).header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(2))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers
                        .header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.counts_by_kind.product_review").value(2))
                .andExpect(jsonPath("$.counts_by_kind.report").value(0))
                .andExpect(jsonPath("$.items[0].summary.audit_id").value(Long.toString(secondAudit)))
                .andExpect(jsonPath("$.items[1].summary.audit_id").value(Long.toString(firstAudit)));
        mvc.perform(get(path("/management/todos")).param("kind", "report").header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0))
                .andExpect(jsonPath("$.items.length()").value(0))
                .andExpect(jsonPath("$.counts_by_kind.product_review").value(2));
        mvc.perform(get(path("/management/todos")).param("page_size", "1").header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(2))
                .andExpect(jsonPath("$.page_size").value(1))
                .andExpect(jsonPath("$.items.length()").value(1));
        mvc.perform(get(path("/management/todos")).header("Origin", ORIGIN).header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", NON_MANAGER_SESSION.toString())))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("MANAGEMENT_NOT_ALLOWED"));
        mvc.perform(get(path("/management/todos")).header("Origin", ORIGIN).header("X-CSRF-Token", CSRF))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTHENTICATION_REQUIRED"));

        mvc.perform(post(path("/admin/cases/" + firstCase + "/claim")).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF).header("Idempotency-Key", "http-claim-no-session"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post(path("/admin/cases/" + firstCase + "/claim")).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF).header("Idempotency-Key", "http-claim-non-manager")
                        .cookie(new jakarta.servlet.http.Cookie("it_session", NON_MANAGER_SESSION.toString())))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("ACTION_NOT_ALLOWED"));

        var claimResponse = mvc.perform(post(path("/admin/cases/" + firstCase + "/claim"))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", CSRF)
                        .header("Idempotency-Key", "http-claim")
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.case_id").value(Long.toString(firstCase)))
                .andExpect(jsonPath("$.case_status").value("claimed"))
                .andExpect(jsonPath("$.claimed_manager_id").value(Long.toString(MANAGER_1)))
                .andExpect(jsonPath("$.already_claimed").value(false))
                .andReturn().getResponse().getContentAsString();
        assertThat(json.readTree(claimResponse).path("claimed_at").stringValue()).isNotBlank();

        mvc.perform(get(path("/admin/product-reviews/" + firstAudit)).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_2_SESSION.toString())))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_VISIBLE"));
        mvc.perform(get(path("/admin/product-reviews/" + firstAudit)).header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.audit_id").value(Long.toString(firstAudit)))
                .andExpect(jsonPath("$.case_id").value(Long.toString(firstCase)))
                .andExpect(jsonPath("$.seller.display_name").value("Seller"))
                .andExpect(jsonPath("$.claim.manager_id").value(Long.toString(MANAGER_1)))
                .andExpect(jsonPath("$.current_content.images[0].file_id").value("1"))
                .andExpect(jsonPath("$.current_content.images[0].url").value("https://files.invalid/1"))
                .andExpect(jsonPath("$.current_content.categories[0].name").value("Existing"));

        mvc.perform(get(path("/management/todos")).param("ownership", "mine").header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF)
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(1))
                .andExpect(jsonPath("$.items[0].case_id").value(Long.toString(firstCase)));

        var decisionResponse = mvc.perform(post(path("/admin/product-reviews/" + firstAudit + "/decision"))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", CSRF)
                        .header("Idempotency-Key", "http-decision")
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString()))
                        .contentType("application/json")
                        .content("{\"decision\":\"approved\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.audit_id").value(Long.toString(firstAudit)))
                .andExpect(jsonPath("$.status").value("passed"))
                .andExpect(jsonPath("$.case_id").value(Long.toString(firstCase)))
                .andExpect(jsonPath("$.case_status").value("decided"))
                .andExpect(jsonPath("$.product.lifecycle_state").value("public"))
                .andReturn().getResponse().getContentAsString();
        var decisionReplay = mvc.perform(post(path("/admin/product-reviews/" + firstAudit + "/decision"))
                        .header("Origin", ORIGIN).header("X-CSRF-Token", CSRF)
                        .header("Idempotency-Key", "http-decision")
                        .cookie(new jakarta.servlet.http.Cookie("it_session", MANAGER_1_SESSION.toString()))
                        .contentType("application/json")
                        .content("{\"decision\":\"approved\"}"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        assertThat(json.readTree(decisionReplay)).isEqualTo(json.readTree(decisionResponse));
        assertThat(secondCase).isNotNull();
    }

    private static Object claimOrError(long manager, UUID session, long caseId, String key,
                                       CountDownLatch ready, CountDownLatch start) throws InterruptedException {
        ready.countDown();
        start.await(5, TimeUnit.SECONDS);
        try {
            return claim(manager, session, caseId, key);
        } catch (BusinessError error) {
            return error;
        }
    }

    private static WriteResult<JsonNode> claim(long manager, UUID session, long caseId, String key) {
        return reviews.claim(context(manager, session), key, caseId);
    }

    private static WriteResult<JsonNode> decide(long manager, UUID session, long auditId, ReviewAction action,
                                                String reason, ReviewAction categoryAction, String categoryReason,
                                                String key) {
        return reviews.decide(context(manager, session), key,
                new ReviewDecisionInput(auditId, action, reason, List.of(BANNED_ITEM), categoryAction,
                        categoryReason));
    }

    private static void withdraw(long caseId, String key) {
        writes.run(context(SELLER, SELLER_SESSION), "review.withdraw", key, caseId, new WithdrawReview());
    }

    private static long submit(long auditId, Instant submittedAt, String title, int contentVersion) {
        writes.run(context(SELLER, SELLER_SESSION), "review.submit", "submit-" + auditId,
                new SubmitRequest(auditId, submittedAt, title, contentVersion), new SubmitReview());
        return CASE_BY_AUDIT.get(auditId);
    }

    private static ExecutionContext context(long account, UUID session) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(account), session, null, 1L, "review-it");
    }

    private static String path(String suffix) {
        return "/api/v1" + suffix;
    }

    private static void insertSession(long account, UUID session) {
        db.sql("INSERT INTO review_session_fixture (session_id, account_id, credential_version) VALUES (?, ?, 1)")
                .param(session).param(account).update();
    }

    private static void createFixtures(Properties properties) throws SQLException {
        var source = new DriverManagerDataSource(properties.getProperty("DATABASE_URL"),
                properties.getProperty("DATABASE_OWNER_USERNAME"), properties.getProperty("DATABASE_OWNER_PASSWORD"));
        fixtureOwner = JdbcClient.create(source);
        fixtureOwner.sql("CREATE SCHEMA " + FIXTURE_SCHEMA).update();
        try (var connection = source.getConnection(); var statement = connection.createStatement()) {
            statement.execute("SET search_path TO " + FIXTURE_SCHEMA);
            new ResourceDatabasePopulator(new ClassPathResource("integration/product-review-fixtures.sql"))
                    .populate(connection);
        }
        String role = fixtureOwner.sql("SELECT quote_ident(?)").param(properties.getProperty("DATABASE_USERNAME"))
                .query(String.class).single();
        fixtureOwner.sql("GRANT USAGE ON SCHEMA " + FIXTURE_SCHEMA + " TO " + role).update();
        fixtureOwner.sql("GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA "
                + FIXTURE_SCHEMA + " TO " + role).update();
        fixtureOwner.sql("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA " + FIXTURE_SCHEMA + " TO " + role)
                .update();
    }

    private static void cleanupCases() {
        for (long caseId : new ArrayList<>(TRACKED_CASES)) {
            db.sql("DELETE FROM moderation_case_action WHERE case_id = ?").param(caseId).update();
            db.sql("DELETE FROM moderation_case WHERE id = ?").param(caseId).update();
        }
        TRACKED_CASES.clear();
    }

    private static void cleanupInfrastructure() {
        // Real notification and realtime event facts are scoped to the fixture seller.
        db.sql("DELETE FROM notification WHERE recipient_account_id = ?").param(SELLER).update();
        db.sql("DELETE FROM user_event WHERE recipient_account_id = ?").param(SELLER).update();
        db.sql("DELETE FROM account_event_head WHERE account_id = ?").param(SELLER).update();
        db.sql("DELETE FROM operation_record WHERE actor_id IN (?, ?, ?, ?)")
                .param(Long.toString(MANAGER_1)).param(Long.toString(MANAGER_2))
                .param(Long.toString(NON_MANAGER)).param(Long.toString(SELLER)).update();
        db.sql("DELETE FROM audit_record WHERE actor_id IN (?, ?, ?, ?)")
                .param(Long.toString(MANAGER_1)).param(Long.toString(MANAGER_2))
                .param(Long.toString(NON_MANAGER)).param(Long.toString(SELLER)).update();
    }

    private static long publicVisible() {
        return db.sql("SELECT count(*) FROM review_public_products WHERE product_id = ?")
                .param(PRODUCT).query(Long.class).single();
    }

    private static String productState() {
        return db.sql("SELECT lifecycle_state FROM review_product_fixture WHERE product_id = ?")
                .param(PRODUCT).query(String.class).single();
    }

    private static String auditStatus(long auditId) {
        return db.sql("SELECT status FROM review_audit_fixture WHERE audit_id = ?")
                .param(auditId).query(String.class).single();
    }

    private static Integer auditReviewedVersion(long auditId) {
        return db.sql("SELECT reviewed_content_version FROM review_audit_fixture WHERE audit_id = ?")
                .param(auditId).query(Integer.class).optional().orElse(null);
    }

    private static String categoryApplicationStatus(long auditId) {
        return db.sql("SELECT status FROM review_category_application_fixture WHERE audit_id = ?")
                .param(auditId).query(String.class).single();
    }

    private static long sellerNotificationCount() {
        return db.sql("SELECT count(*) FROM notification WHERE recipient_account_id = ?")
                .param(SELLER).query(Long.class).single();
    }

    private static NotificationRow notification(long auditId) {
        return db.sql("""
                SELECT notification_id, recipient_account_id, event_type, source_type, source_id, intent_key,
                       display_params -> 'values' ->> 'decision' AS decision,
                       display_params -> 'values' ->> 'reason' AS reason
                FROM notification
                WHERE recipient_account_id = ? AND source_type = 'product_audit' AND source_id = ?
                """).param(SELLER).param(auditId)
                .query((row, index) -> new NotificationRow(row.getLong("notification_id"),
                        row.getLong("recipient_account_id"), row.getString("event_type"),
                        row.getString("source_type"), row.getLong("source_id"), row.getString("intent_key"),
                        row.getString("decision"), row.getString("reason")))
                .single();
    }

    private static String notificationRowAsJson(long notificationId) {
        return db.sql("SELECT to_jsonb(n)::text FROM notification n WHERE notification_id = ?")
                .param(notificationId).query(String.class).single();
    }

    /**
     * Counts the delivery events that announce this notification, addressed to the seller and
     * carrying the product-audit business source in the SQL columns.
     */
    private static long createdNotificationEvents(long auditId, long notificationId) {
        return db.sql("""
                SELECT count(*) FROM user_event
                WHERE event_type = 'notification_created'
                  AND recipient_account_id = ?
                  AND payload_type = 'notification'
                  AND payload_id = ?
                  AND source_type = 'product_audit'
                  AND source_id = ?
                  AND intent_key = ?
                """).param(SELLER).param(notificationId).param(auditId)
                .param(notificationIntentKey(auditId)).query(Long.class).single();
    }

    private static long sellerCreatedNotificationEvents() {
        return db.sql("""
                SELECT count(*) FROM user_event
                WHERE event_type = 'notification_created' AND recipient_account_id = ?
                """).param(SELLER).query(Long.class).single();
    }

    private static long insertConflictingNotification(long auditId) {
        var displayParams = json.createObjectNode();
        var values = displayParams.putObject("values");
        values.put("product_id", Long.toString(PRODUCT));
        values.put("decision", "rejected");
        values.put("reason", "previous conflict");
        return db.sql("""
                INSERT INTO notification
                    (recipient_account_id, intent_key, event_type, source_type, source_id, template_key,
                     template_version, display_params, occurred_at, created_at)
                VALUES (?, ?, 'product_audit.rejected', 'product_audit', ?, 'product_audit.decision', '1',
                        CAST(? AS jsonb), statement_timestamp() - interval '1 minute', statement_timestamp())
                RETURNING notification_id
                """).param(SELLER).param(notificationIntentKey(auditId)).param(auditId)
                .param(json.writeValueAsString(displayParams))
                .query(Long.class).single();
    }

    private static String notificationIntentKey(long auditId) {
        return "product_audit.decision:" + auditId;
    }

    private static long caseActionCount(long caseId, String actionKind) {
        return db.sql("SELECT count(*) FROM moderation_case_action WHERE case_id = ? AND action_kind = ?")
                .param(caseId).param(actionKind).query(Long.class).single();
    }

    private static long caseAuditCount(long caseId) {
        return db.sql("SELECT count(*) FROM audit_record WHERE target_type = 'product_audit' AND basis_type = 'case' "
                        + "AND basis_id = ?").param(caseId).query(Long.class).single();
    }

    private static long claimedManager(long caseId) {
        return db.sql("SELECT claimed_manager_id FROM moderation_case WHERE id = ?")
                .param(caseId).query(Long.class).single();
    }

    private static long operationCount(String key) {
        return db.sql("SELECT count(*) FROM operation_record WHERE idempotency_key = ?")
                .param(key).query(Long.class).single();
    }

    private static long auditCount(java.util.UUID operationId) {
        return db.sql("SELECT count(*) FROM audit_record WHERE operation_id = ?")
                .param(operationId).query(Long.class).single();
    }

    record NotificationRow(long notificationId, long recipientAccountId, String eventType, String sourceType,
                           long sourceId, String intentKey, String decision, String reason) {
    }

    record SubmitRequest(long auditId, Instant submittedAt, String title, int contentVersion) {
    }

    static final class SubmitReview implements WriteExecutor.UseCase<SubmitRequest, Boolean> {
        @Override
        public JsonNode digestInput(SubmitRequest request) {
            return json.createObjectNode().put("audit_id", request.auditId()).put("title", request.title())
                    .put("content_version", request.contentVersion());
        }

        @Override
        public LockPlan prepare(ExecutionContext context, SubmitRequest request) {
            return new LockPlan(Map.of(), Set.of());
        }

        @Override
        public Boolean qualify(ExecutionContext context, SubmitRequest request, LockPlan plan) {
            return Boolean.TRUE;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, Boolean qualifications, ResourceRef resource) {
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, SubmitRequest request,
                                             Boolean qualifications, LockPlan plan) {
            long caseId = cases.open(transaction, request.submittedAt());
            db.sql("""
                    INSERT INTO review_audit_fixture (audit_id, case_id, product_id, status, submitted_at)
                    VALUES (?, ?, ?, 'pending', ?)
                    """).param(request.auditId()).param(caseId).param(PRODUCT)
                    .param(java.sql.Timestamp.from(request.submittedAt())).update();
            db.sql("""
                    UPDATE review_product_fixture
                    SET title = ?, content_version = ?, lifecycle_state = 'pending_review'
                    WHERE product_id = ?
                    """).param(request.title()).param(request.contentVersion()).param(PRODUCT).update();
            TRACKED_CASES.add(caseId);
            CASE_BY_AUDIT.put(request.auditId(), caseId);
            var body = json.createObjectNode().put("audit_id", Long.toString(request.auditId()))
                    .put("case_id", Long.toString(caseId));
            return new WriteResult.Response<>(201, body, new ResourceRef("case", caseId));
        }
    }

    static final class WithdrawReview implements WriteExecutor.UseCase<Long, Boolean> {
        @Override
        public JsonNode digestInput(Long request) {
            return json.createObjectNode().put("case_id", request);
        }

        @Override
        public LockPlan prepare(ExecutionContext context, Long request) {
            return plan(request).lockPlan();
        }

        @Override
        public Boolean qualify(ExecutionContext context, Long request, LockPlan plan) {
            return Boolean.TRUE;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, Boolean qualifications, ResourceRef resource) {
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, Long request, Boolean qualifications,
                                             LockPlan prepared) {
            var plan = plan(request);
            plan.acquire(transaction);
            var audit = port.auditByCase(request);
            port.lockAudit(audit.auditId());
            cases.requireUnclaimed(transaction, request);
            db.sql("UPDATE review_audit_fixture SET status = 'withdrawn' WHERE audit_id = ?")
                    .param(audit.auditId()).update();
            db.sql("UPDATE review_product_fixture SET lifecycle_state = 'off_shelf' WHERE product_id = ?")
                    .param(PRODUCT).update();
            return new WriteResult.Response<>(200, json.createObjectNode().put("case_id", Long.toString(request)),
                    new ResourceRef("case", request));
        }

        private SubjectPlan plan(long caseId) {
            var audit = port.auditByCase(caseId);
            var auditKey = new LockPlan.Key(LockPlan.Domain.PRODUCT_AUDIT, List.of(audit.auditId()));
            return SubjectPlan.resource(auditKey, transaction -> port.lockAudit(audit.auditId()))
                    .merge(SubjectPlan.resource(ProductReviewCases.lockKey(caseId), transaction -> {
                    }));
        }
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class Fixtures {
        @Bean
        ProductReviewFixturePort.LockTrace lockTrace() {
            return new ProductReviewFixturePort.LockTrace();
        }

        @Bean
        ProductReviewFixturePort fixturePort(JdbcClient db, ProductReviewFixturePort.LockTrace trace) {
            return new ProductReviewFixturePort(db, trace);
        }

        @Bean
        CsrfGuard.Verifier csrfVerifier() {
            return (request, token) -> CSRF.equals(token);
        }

        // Trade is outside this test's scope; the composition baseline supplies the real ports in
        // S3-02/S4. Mocked here so the review workflow can start the full application context.
        @Bean
        TradePorts.Product tradeProduct() {
            return org.mockito.Mockito.mock(TradePorts.Product.class);
        }

        @Bean
        TradePorts.Accounts tradeAccounts() {
            return org.mockito.Mockito.mock(TradePorts.Accounts.class);
        }

        @Bean
        TradePorts.Cases tradeCases() {
            return org.mockito.Mockito.mock(TradePorts.Cases.class);
        }

        @Bean
        TradePorts.Notifications tradeNotifications() {
            return org.mockito.Mockito.mock(TradePorts.Notifications.class);
        }

        @Bean
        TradeActorResolver tradeActorResolver() {
            return request -> {
                throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "fixture");
            };
        }
    }
}
