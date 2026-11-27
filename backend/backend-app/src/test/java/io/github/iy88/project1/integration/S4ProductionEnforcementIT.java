package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.AccountCookies;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Exercises case decisions through the normal HTTP entry points and production subject adapters. */
class S4ProductionEnforcementIT {
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String PASSWORD = "S4ProductionFixture920!";
    private static final String RUN = UUID.randomUUID().toString();
    private static final List<SessionService.Issued> SESSIONS = new ArrayList<>();
    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static JsonMapper json;
    private static HttpClient http;
    private static String baseUrl;

    @BeforeAll
    static void start() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        properties.setProperty("REDIS_NAMESPACE", properties.getProperty("REDIS_NAMESPACE") + ":s4-production:" + RUN);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("OSS_ENDPOINT", "https://oss-evidence.example.invalid");
        var application = new SpringApplication(BackendAppApplication.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("s4-production-enforcement-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        var port = ((ServletWebServerApplicationContext) app).getWebServer().getPort();
        baseUrl = "http://127.0.0.1:" + port + "/api/v1";
        db = app.getBean(JdbcClient.class);
        json = app.getBean(JsonMapper.class);
        http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }

    @AfterAll
    static void stop() {
        if (app == null) {
            return;
        }
        try (var context = app; var client = http) {
            var sessions = context.getBean(SessionService.class);
            SESSIONS.forEach(session -> sessions.revoke(sessions.authenticate(session.token())));
            // The integration database is provisioned and discarded by the runner.
        }
    }

    @Test
    void explicitLiftUnfreezesOnlyItsRecordedSource() throws Exception {
        var buyer = login("lift-buyer", "user");
        var seller = login("lift-seller", "user");
        var manager = login("lift-manager", "manager");
        var otherManager = login("lift-other", "manager");
        long trade = activeTrade(buyer, seller);

        long first = claimedTradeCase(buyer, manager, trade);
        var freeze = post(manager, decisionPath(first), decision(freeze(trade)), key(), 201);
        String enforcement = freeze.at("/enforcements/0/enforcement_id").asString();
        assertThat(freeze.at("/enforcements/0/result_ref").asString()).startsWith("trade_transition:");
        db.sql("update case_enforcement set result_type = 'trade', result_id = ? where case_id = ? and enforcement_id = ?")
                .param(trade).param(first).param(enforcement).update();
        long second = claimedTradeCase(seller, otherManager, trade);
        var secondFreeze = post(otherManager, decisionPath(second), decision(freeze(trade)), key(), 201);
        assertThat(activeSources(trade)).containsExactlyInAnyOrder(first, second);

        String original = "/admin/cases/" + first + "/enforcements/" + enforcement + "/lift";
        String reason = "{\"reason\":\"已复核并解除本来源\"}";
        assertThat(post(otherManager, original, reason, key(), 404).at("/error/code").asString())
                .isEqualTo("NOT_CASE_MANAGER");
        String liftKey = key();
        var lifted = post(manager, original, reason, liftKey, 200);
        assertThat(lifted.path("enforcement_id").asString()).isEqualTo(enforcement);
        assertThat(lifted.path("remaining_restrictions").isEmpty()).isFalse();
        assertThat(post(manager, original, reason, liftKey, 200)).isEqualTo(lifted);
        assertThat(activeSources(trade)).containsExactly(second);
        assertThat(db.sql("""
                select count(*) from trade_state_history where trade_id = ? and case_id = ? and action = 'trade.unfreeze'
                """).param(trade).param(first).query(Long.class).single()).isEqualTo(1);
        String secondEnforcement = secondFreeze.at("/enforcements/0/enforcement_id").asString();
        var last = post(otherManager, "/admin/cases/" + second + "/enforcements/" + secondEnforcement + "/lift",
                reason, key(), 200);
        assertThat(last.path("remaining_restrictions").isEmpty()).isTrue();
        assertThat(activeSources(trade)).isEmpty();
    }

    @Test
    void decisionLiftsTheCaseTimeoutSourceAndKeepsAnOtherCaseFreeze() throws Exception {
        var buyer = login("timeout-lift-buyer", "user");
        var seller = login("timeout-lift-seller", "user");
        var manager = login("timeout-lift-manager", "manager");
        var otherManager = login("timeout-lift-other", "manager");
        long trade = activeTrade(buyer, seller);
        long timeoutCase = claimedTradeCase(buyer, manager, trade);
        long timeoutFreeze = db.sql("""
                insert into trade_freeze (trade_id, source, source_ref, reason, started_at)
                values (?, 'timeout', ?, '单方确认超时', now()) returning id
                """).param(trade).param(timeoutCase).query(Long.class).single();
        db.sql("update trade set status = 'abnormal' where id = ?").param(trade).update();

        long otherCase = claimedTradeCase(seller, otherManager, trade);
        post(otherManager, decisionPath(otherCase), decision(freeze(trade)), key(), 201);
        assertThat(activeSources(trade)).containsExactlyInAnyOrder(timeoutCase, otherCase);

        long unrelatedTrade = activeTrade(buyer, seller);
        var wrongTarget = post(manager, decisionPath(timeoutCase), noAction(lift(unrelatedTrade)), key(), 409);
        assertThat(wrongTarget.at("/error/code").asString()).isEqualTo("TARGET_STATE_CONFLICT");
        assertThat(activeSources(trade)).containsExactlyInAnyOrder(timeoutCase, otherCase);

        String idempotency = key();
        var lifted = post(manager, decisionPath(timeoutCase), noAction(lift(trade)), idempotency, 201);
        assertThat(lifted.path("decision_kind").asString()).isEqualTo("no_action");
        assertThat(lifted.at("/enforcements/0/action").asString()).isEqualTo("lift_trade_freeze");
        assertThat(lifted.at("/enforcements/0/current_state").asString()).contains("frozen=true");
        assertThat(post(manager, decisionPath(timeoutCase), noAction(lift(trade)), idempotency, 201))
                .isEqualTo(lifted);
        assertThat(activeSources(trade)).containsExactly(otherCase);
        assertThat(db.sql("select status from trade where id = ?").param(trade)
                .query(String.class).single()).isEqualTo("abnormal");
        assertThat(db.sql("select ended_at is not null from trade_freeze where id = ?")
                .param(timeoutFreeze).query(Boolean.class).single()).isTrue();
        assertThat(db.sql("select count(*) from trade_freeze where trade_id = ? and ended_at is null")
                .param(trade).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("""
                select count(*) from trade_state_history
                where trade_id = ? and case_id = ? and action = 'trade.unfreeze'
                """).param(trade).param(timeoutCase).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("""
                select count(*) from notification
                where source_type = 'case' and source_id = ? and event_type = 'case.trade_unfrozen'
                """).param(timeoutCase).query(Long.class).single()).isEqualTo(2);
    }

    @Test
    void noActionDecisionRestoresTimedOutTradeAndCompletionConfirmationRestartsTheWait() throws Exception {
        var buyer = login("timeout-confirm-buyer", "user");
        var seller = login("timeout-confirm-seller", "user");
        var manager = login("timeout-confirm-manager", "manager");
        long trade = activeTrade(buyer, seller);
        long agreement = effectiveAgreement(trade, buyer.account().id());
        db.sql("""
                insert into trade_confirmation (trade_id, agreement_id, confirmer_id, submitted_at,
                                                business_event_id)
                values (?, ?, ?, now() - interval '8 days', gen_random_uuid())
                """).param(trade).param(agreement).param(buyer.account().id()).update();
        db.sql("""
                insert into confirmation_wait
                    (trade_id, started_at, active_since, accumulated_seconds, wait_seconds, policy_version,
                     ended_at, end_reason)
                values (?, now() - interval '8 days', null, 604800, 604800, 's2-v1', now(), 'timeout')
                """).param(trade).update();
        long caseId = claimedTradeCase(buyer, manager, trade);
        long timeoutFreeze = db.sql("""
                insert into trade_freeze (trade_id, source, source_ref, reason, started_at)
                values (?, 'timeout', ?, '单方确认超时', now()) returning id
                """).param(trade).param(caseId).query(Long.class).single();
        db.sql("update trade set status = 'abnormal' where id = ?").param(trade).update();

        var decided = post(manager, decisionPath(caseId), noAction("""
                {"action":"adjust_trade_status","target_type":"trade","target_id":"%d","expected_result":"in_progress"},
                {"action":"lift_trade_freeze","target_type":"trade","target_id":"%d"}
                """.formatted(trade, trade)), key(), 201);

        assertThat(decided.path("decision_kind").asString()).isEqualTo("no_action");
        assertThat(decided.path("enforcements").size()).isEqualTo(2);
        assertThat(db.sql("select status from trade where id = ?").param(trade).query(String.class).single())
                .isEqualTo("in_progress");
        assertThat(activeSources(trade)).isEmpty();
        assertThat(db.sql("select ended_at is not null from trade_freeze where id = ?")
                .param(timeoutFreeze).query(Boolean.class).single()).isTrue();

        int version = db.sql("select version from trade where id = ?").param(trade).query(Integer.class).single();
        var confirmation = post(buyer, "/trades/" + trade + "/completion-confirmations", """
                {"note":"恢复后重新提交完成确认","expected_version":%d}
                """.formatted(version), key(), 201);
        assertThat(confirmation.at("/trade/status").asString()).isEqualTo("in_progress");
        assertThat(db.sql("""
                select active_since is not null and ended_at is null and wait_seconds = 604800
                       and accumulated_seconds = 0
                from confirmation_wait where trade_id = ?
                """).param(trade).query(Boolean.class).single()).isTrue();
    }

    @Test
    void decisionLiftResumesThePausedWaitOnlyAfterTheLastCaseSource() throws Exception {
        var buyer = login("timing-lift-buyer", "user");
        var seller = login("timing-lift-seller", "user");
        var manager = login("timing-lift-manager", "manager");
        long trade = activeTrade(buyer, seller);
        long agreement = db.sql("""
                insert into agreement_version
                    (trade_id, version_no, status, proposed_by, delivery_at, delivery_place_text,
                     delivery_method, amount_cents, payment_method, payment_timing, proposed_at,
                     business_event_id)
                values (?, 1, 'effective', ?, now(), 'fixture place', 'face_to_face', 100,
                        'offline', 'on_delivery', now(), gen_random_uuid())
                returning id
                """).param(trade).param(buyer.account().id()).query(Long.class).single();
        db.sql("update trade set status = 'in_progress', active_agreement_id = ? where id = ?")
                .param(agreement).param(trade).update();
        db.sql("""
                insert into trade_confirmation (trade_id, agreement_id, confirmer_id, submitted_at,
                                                business_event_id)
                values (?, ?, ?, now() - interval '2 days', gen_random_uuid())
                """).param(trade).param(agreement).param(buyer.account().id()).update();
        db.sql("""
                insert into confirmation_wait
                    (trade_id, started_at, active_since, accumulated_seconds, wait_seconds, policy_version)
                values (?, now() - interval '2 days', null, 172800, 604800, 's2-v1')
                """).param(trade).update();
        long caseId = claimedTradeCase(buyer, manager, trade);
        db.sql("""
                insert into trade_freeze (trade_id, source, source_ref, reason, started_at)
                values (?, 'admin_case', ?, '处置冻结', now())
                """).param(trade).param(caseId).update();

        var lifted = post(manager, decisionPath(caseId), decision(lift(trade)), key(), 201);

        assertThat(lifted.at("/enforcements/0/previous_state").asString()).contains("frozen=true");
        assertThat(lifted.at("/enforcements/0/current_state").asString()).contains("frozen=false");
        assertThat(activeSources(trade)).isEmpty();
        assertThat(db.sql("select status from trade where id = ?").param(trade)
                .query(String.class).single()).isEqualTo("in_progress");
        assertThat(db.sql("""
                select active_since is not null and ended_at is null and accumulated_seconds = 172800
                from confirmation_wait where trade_id = ?
                """).param(trade).query(Boolean.class).single()).isTrue();
        assertThat(db.sql("""
                select count(*) from task_schedule
                where task_kind = 'trade.timeout' and source_id = ?
                  and completed_at is null and cancelled_at is null
                """).param(trade).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("""
                select count(*) from trade_state_history
                where trade_id = ? and case_id = ? and action = 'trade.unfreeze'
                """).param(trade).param(caseId).query(Long.class).single()).isEqualTo(1);
    }

    @Test
    void decisionAcquiresTheCombinedLockPlanAndCommitsBothTradeActions() throws Exception {
        var buyer = login("batch-buyer", "user");
        var seller = login("batch-seller", "user");
        var manager = login("batch-manager", "manager");
        long trade = activeTrade(buyer, seller);
        long caseId = claimedTradeCase(buyer, manager, trade);
        var terminate = """
                {"action":"adjust_trade_status","target_type":"trade","target_id":"%s","expected_result":"terminated"}
                """.formatted(trade);
        var response = post(manager, decisionPath(caseId), decision(freeze(trade) + "," + terminate),
                key(), 201);
        assertThat(response.path("enforcements").size()).isEqualTo(2);
        assertThat(db.sql("select status from trade where id = ?").param(trade).query(String.class).single())
                .isEqualTo("terminated");
        assertThat(activeSources(trade)).isEmpty();
        assertThat(db.sql("select archived_at is not null from trade_conversation where trade_id = ?")
                .param(trade).query(Boolean.class).single()).isTrue();
    }

    @Test
    void secondTradeActionFailureRollsBackTheDecisionAndFirstAction() throws Exception {
        var buyer = login("rollback-buyer", "user");
        var seller = login("rollback-seller", "user");
        var manager = login("rollback-manager", "manager");
        long trade = activeTrade(buyer, seller);
        long caseId = claimedTradeCase(buyer, manager, trade);
        String invalid = """
                {"action":"adjust_trade_status","target_type":"trade","target_id":"%d","expected_result":"in_progress"}
                """.formatted(trade);
        var rejected = post(manager, decisionPath(caseId), decision(freeze(trade) + "," + invalid),
                key(), 409);
        assertThat(rejected.at("/error/code").asString()).isEqualTo("TRANSITION_NOT_ALLOWED");
        assertThat(activeSources(trade)).isEmpty();
        assertThat(db.sql("select case_status from moderation_case where id = ?").param(caseId)
                .query(String.class).single()).isEqualTo("claimed");
        assertThat(db.sql("select count(*) from case_enforcement where case_id = ?").param(caseId)
                .query(Long.class).single()).isZero();
        assertThat(db.sql("""
                select count(*) from notification where source_type = 'case' and source_id = ?
                  and event_type = 'management.case_decide'
                """).param(caseId).query(Long.class).single()).isZero();
        assertThat(db.sql("""
                select count(*) from notification where source_type = 'case' and source_id = ?
                  and event_type not like 'management.%'
                """).param(caseId).query(Long.class).single()).isZero();
    }

    @Test
    void appealReversalRequiresAnExplicitOriginalAndPreservesTheOtherDisposition() throws Exception {
        var buyer = login("appeal-buyer", "user");
        var seller = login("appeal-seller", "user");
        var manager = login("appeal-manager", "manager");
        var otherManager = login("appeal-other", "manager");
        long trade = activeTrade(buyer, seller);
        long product = db.sql("select product_id from trade where id = ?")
                .param(trade).query(Long.class).single();
        long caseId = claimedTradeCase(buyer, manager, trade);
        String withdraw = """
                {"action":"withdraw_public_access","target_type":"product","target_id":"%d"}
                """.formatted(product);
        var decided = post(manager, decisionPath(caseId), decision(freeze(trade) + "," + withdraw), key(), 201);
        var enforcements = decided.path("enforcements");
        String freezeId = enforcements.path(0).path("enforcement_id").asString();
        String displayId = enforcements.path(1).path("enforcement_id").asString();
        String casePath = "/cases/" + caseId;
        String messagePath = casePath + "/messages";
        var appealBody = json.createObjectNode().put("message_kind", "appeal").put("body", "请复核该处置");
        var thread = get(seller, casePath, 200).path("thread");
        appealBody.set("thread", thread);
        var appeal = post(seller, messagePath, appealBody.toString(), key(), 201);
        String appealId = appeal.path("case_action_id").asString();
        var pending = get(manager, casePath, 200).at("/pending_appeals/0/original_enforcements");
        assertThat(pending.valueStream().map(item -> item.path("enforcement_id").asString()).toList())
                .containsExactlyInAnyOrder(freezeId, displayId);
        assertThat(get(seller, casePath, 200).path("pending_appeals").isMissingNode()).isTrue();
        var reply = json.createObjectNode().put("message_kind", "manager_reply").put("body", "已复核")
                .put("appeal_action_id", appealId).put("resolution", "revoke").put("basis_ref", "case:" + caseId);
        reply.set("thread", thread);
        post(manager, messagePath, reply.toString(), key(), 422);
        reply.put("original_enforcement_id", freezeId);
        post(otherManager, messagePath, reply.toString(), key(), 404);

        reply.put("resolution", "adjust");
        reply.putArray("replacement_enforcements").addObject().put("action", "adjust_trade_status")
                .put("target_type", "trade").put("target_id", Long.toString(trade)).put("expected_result", "in_progress");
        post(manager, messagePath, reply.toString(), key(), 409);
        assertThat(activeSources(trade)).containsExactly(caseId);
        assertThat(get(manager, casePath, 200).path("pending_appeals").size()).isEqualTo(1);
        assertThat(db.sql("select lifted_at is null from case_enforcement where enforcement_id = ?")
                .param(freezeId).query(Boolean.class).single()).isTrue();
        assertThat(db.sql("""
                        select count(*) from moderation_case_action
                        where case_id = ? and action_kind = 'manager_reply'
                        """).param(caseId).query(Long.class).single()).isZero();
        assertThat(db.sql("""
                        select count(*) from case_enforcement
                        where case_id = ? and action = 'lift_trade_freeze'
                        """).param(caseId).query(Long.class).single()).isZero();
        assertThat(db.sql("""
                        select count(*) from notification
                        where source_type = 'case' and source_id = ?
                          and event_type in ('case.trade_unfrozen', 'case.appeal_resolved')
                        """).param(caseId).query(Long.class).single()).isZero();

        reply.put("resolution", "revoke");
        reply.remove("replacement_enforcements");
        String idempotencyKey = key();
        var resolved = post(manager, messagePath, reply.toString(), idempotencyKey, 201);
        assertThat(post(manager, messagePath, reply.toString(), idempotencyKey, 201)).isEqualTo(resolved);
        assertThat(activeSources(trade)).isEmpty();
        assertThat(get(manager, casePath, 200).path("pending_appeals").isEmpty()).isTrue();
        assertThat(db.sql("select lifted_at is null from case_enforcement where enforcement_id = ?")
                .param(displayId).query(Boolean.class).single()).isTrue();
        get(buyer, "/products/" + product, 404);
    }

    @Test
    void contentRemovalUsesTheExactReportedCommentAndOnlyNotifiesItsAuthor() throws Exception {
        var seller = login("content-seller", "user");
        var reporter = login("content-reporter", "user");
        var author = login("content-author", "user");
        var manager = login("content-manager", "manager");
        long product = publicProduct(seller);
        String comments = "/products/" + product + "/comments";
        long reported = post(author, comments, "{\"body\":\"需要核实的评论原文\"}", key(), 201).path("id").asLong();
        long other = post(author, comments, "{\"body\":\"同商品的其他评论\"}", key(), 201).path("id").asLong();
        long caseId = claimedCase(reporter, manager, "comment", reported);
        String remove = "{\"action\":\"remove_content\",\"target_type\":\"comment\",\"target_id\":\"%d\"}";
        post(manager, decisionPath(caseId), decision(remove.formatted(other)), key(), 403);
        var decided = post(manager, decisionPath(caseId), decision(remove.formatted(reported)), key(), 201);
        assertThat(decided.at("/enforcements/0/result_ref").asString()).isEqualTo("product_comment:" + reported);
        assertThat(get(reporter, comments, 200).toString()).contains("同商品的其他评论").doesNotContain("需要核实的评论原文");
        assertThat(db.sql("select body from product_comment where comment_id = ?")
                .param(reported).query(String.class).single()).isEqualTo("需要核实的评论原文");
        assertThat(db.sql("""
                        select recipient_account_id from notification
                        where source_type = 'case' and source_id = ? and event_type = 'case.content_removed'
                        """).param(caseId).query(Long.class).list()).containsExactly(author.account().id());
    }

    @Test
    void claimedManagerRestoresAbnormalTradeWithoutChangingOccupancy() throws Exception {
        var buyer = login("restore-buyer", "user");
        var seller = login("restore-seller", "user");
        var manager = login("restore-manager", "manager");
        long trade = activeTrade(buyer, seller);
        db.sql("update trade set status = 'abnormal' where id = ?").param(trade).update();
        long caseId = claimedTradeCase(buyer, manager, trade);
        var result = post(manager, decisionPath(caseId), decision("""
                {"action":"adjust_trade_status","target_type":"trade","target_id":"%d","expected_result":"in_progress"}
                """.formatted(trade)), key(), 201);
        assertThat(result.at("/enforcements/0/result_ref").asString()).startsWith("trade_transition:");
        assertThat(result.path("decided_at").asString()).isNotBlank();
        assertThat(result.at("/enforcements/0/affected_scope").isArray()).isTrue();
        assertThat(db.sql("select status from trade where id = ?").param(trade).query(String.class).single())
                .isEqualTo("in_progress");
        assertThat(db.sql("""
                select p.occupied_by_trade_id from product p join trade t on t.product_id = p.product_id where t.id = ?
                """).param(trade).query(Long.class).single()).isEqualTo(trade);
        assertThat(db.sql("""
                select recipient_account_id from notification where source_type = 'trade' and source_id = ?
                  and event_type = 'trade.restored'
                """).param(trade).query(Long.class).list()).containsExactlyInAnyOrder(
                        buyer.account().id(), seller.account().id());
        assertThat(db.sql("""
                select count(*) from notification where source_type = 'case' and source_id = ?
                  and event_type not like 'management.%'
                """).param(caseId).query(Long.class).single()).isZero();
    }

    @Test
    void evaluationRemovalHidesContentAndKeepsTheExactSnapshotForTheClaimant() throws Exception {
        var buyer = login("review-buyer", "user");
        var seller = login("review-seller", "user");
        var manager = login("review-manager", "manager");
        long trade = activeTrade(buyer, seller);
        db.sql("update trade set status = 'completed', terminal_reason = 'completed', ended_at = now() where id = ?")
                .param(trade).update();
        String reviews = "/trades/" + trade + "/reviews";
        long review = post(buyer, reviews, "{\"rating\":3,\"content\":\"仅承办可读的评价原文\"}", key(), 201)
                .at("/review/review_id").asLong();
        assertThat(get(seller, reviews, 200).toString()).contains("仅承办可读的评价原文");
        long caseId = claimedCase(seller, manager, "evaluation", review);
        var decision = post(manager, decisionPath(caseId), decision("""
                {"action":"remove_evaluation_content","target_type":"evaluation","target_id":"%d"}
                """.formatted(review)), key(), 201);
        assertThat(decision.at("/enforcements/0/result_ref").asString()).isEqualTo("trade_review:" + review);
        assertThat(get(seller, reviews, 200).toString()).doesNotContain("仅承办可读的评价原文");
        assertThat(get(seller, "/cases/" + caseId, 200).path("target").isMissingNode()).isTrue();
        assertThat(get(manager, "/cases/" + caseId, 200).at("/target/body").asString()).isEqualTo("仅承办可读的评价原文");
    }

    @Test
    void purchaseAndClaimedCaseKeepTheirOwnCapturedProductVersions() throws Exception {
        var seller = login("snapshot-seller", "user");
        var buyer = login("snapshot-buyer", "user");
        var manager = login("snapshot-manager", "manager");
        long product = publicProduct(seller);
        String path = "/products/" + product;
        long trade = post(buyer, path + "/purchase-requests", """
                {"expected_product_version":1}
                """, key(), 201).path("id").asLong();
        db.sql("update product set title = ?, content_version = 2 where product_id = ?")
                .param("Case version").param(product).update();
        long caseId = claimedCase(buyer, manager, "product", product);
        db.sql("update product set title = ?, content_version = 3 where product_id = ?")
                .param("Current version").param(product).update();
        post(seller, path + "/off-shelf", """
                {"expected_version":3}
                """, key(), 200);

        var purchase = get(buyer, path + "?trade_id=" + trade, 200);
        assertThat(purchase.path("title").asString()).isEqualTo("Trade fixture");
        assertThat(purchase.path("content_version").asInt()).isEqualTo(1);
        var report = get(manager, path + "?case_id=" + caseId, 200);
        assertThat(report.path("title").asString()).isEqualTo("Case version");
        assertThat(report.path("content_version").asInt()).isEqualTo(2);
        assertThat(get(seller, path, 200).path("title").asString()).isEqualTo("Current version");
        db.sql("""
                insert into product_edit_history
                       (product_id, operator_kind, operator_account_id, edit_kind, before_content, after_content,
                        reason, basis_type, basis_id)
                values (?, 'admin', ?, 'category_correction', '{"category_ids":["1"]}', '{"category_ids":["2"]}',
                        'case correction', 'case', ?)
                """).param(product).param(manager.account().id()).param(caseId).update();
        db.sql("""
                insert into product_edit_history
                       (product_id, operator_kind, operator_account_id, edit_kind, before_content, after_content)
                values (?, 'seller', ?, 'content_edit', '{"title":"Case version"}', '{"title":"Current version"}')
                """).param(product).param(seller.account().id()).update();
        var history = get(manager, path + "/edit-history?case_id=" + caseId, 200);
        assertThat(history.path("total").asInt()).isEqualTo(1);
        assertThat(history.at("/items/0/edit_kind").asString()).isEqualTo("category_correction");
    }

    @Test
    void sellerOffShelfClosesOnlyPendingRequestsForThatProduct() throws Exception {
        var seller = login("off-shelf-seller", "user");
        var first = login("off-shelf-first", "user");
        var second = login("off-shelf-second", "user");
        long product = publicProduct(seller);
        long otherProduct = publicProduct(seller);
        String purchase = "{\"expected_product_version\":1}";
        long firstRequest = post(first, "/products/" + product + "/purchase-requests",
                purchase, key(), 201).path("id").asLong();
        long secondRequest = post(second, "/products/" + product + "/purchase-requests",
                purchase, key(), 201).path("id").asLong();
        long unrelated = post(first, "/products/" + otherProduct + "/purchase-requests",
                purchase, key(), 201).path("id").asLong();

        String path = "/products/" + product + "/off-shelf";
        String expected = "{\"expected_version\":1}";
        String idempotencyKey = key();
        var response = post(seller, path, expected, idempotencyKey, 200);
        assertThat(response.path("closed_pending_request_count").asInt()).isEqualTo(2);
        assertThat(post(seller, path, expected, idempotencyKey, 200)).isEqualTo(response);
        assertThat(db.sql("""
                        select count(*) from audit_record
                        where action = 'product.off_shelf' and target_type = 'product' and target_id = ?
                        """).param(product).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("select lifecycle_state from product where product_id = ?")
                .param(product).query(String.class).single()).isEqualTo("off_shelf");
        assertThat(db.sql("""
                        select count(*) from trade t join trade_conversation c on c.trade_id = t.id
                        where t.id in (?, ?) and t.status = 'closed'
                          and t.close_reason = 'product_delisted' and c.archived_at is not null
                        """).param(firstRequest).param(secondRequest).query(Long.class).single()).isEqualTo(2);
        assertThat(db.sql("select status from trade where id = ?")
                .param(unrelated).query(String.class).single()).isEqualTo("pending_acceptance");
    }

    @Test
    void passwordResetUsesTheSamePublicBudgetForKnownAndUnknownAddresses() throws Exception {
        var account = login("reset-known", "user");
        String knownEmail = account.account().email();
        String unknownEmail = "reset-unknown-" + RUN + "@example.invalid";
        var known = requestPasswordReset(knownEmail);
        var unknown = requestPasswordReset(unknownEmail);
        assertThat(known.statusCode()).isEqualTo(202);
        assertThat(unknown.statusCode()).isEqualTo(202);
        assertThat(unknown.headers().firstValue("Retry-After")).isEqualTo(known.headers().firstValue("Retry-After"));
        var knownBody = json.readTree(known.body());
        var unknownBody = json.readTree(unknown.body());
        assertThat(knownBody.path("requests").size()).isEqualTo(1);
        assertThat(unknownBody.path("requests").size()).isEqualTo(1);
        assertThat(unknownBody.at("/requests/0/purpose")).isEqualTo(knownBody.at("/requests/0/purpose"));
        long knownVerification = knownBody.at("/requests/0/verification_id").asLong();
        long unknownVerification = unknownBody.at("/requests/0/verification_id").asLong();
        assertThat(unknownVerification).isNotEqualTo(knownVerification);
        assertThat(db.sql("select count(*) from email_verification where id = ?")
                .param(unknownVerification).query(Long.class).single()).isZero();
        assertThat(db.sql("select count(*) from email_verification where id = ?")
                .param(knownVerification).query(Long.class).single()).isEqualTo(1);

        for (String email : List.of(knownEmail, unknownEmail)) {
            var repeat = requestPasswordReset(email);
            assertThat(repeat.statusCode()).isEqualTo(429);
            assertThat(Integer.parseInt(repeat.headers().firstValue("Retry-After").orElseThrow())).isPositive();
            assertThat(json.readTree(repeat.body()).at("/error/code").asString()).isEqualTo("RATE_LIMITED");
        }
    }

    @Test
    void accountRestrictionsStackAndOnlyReleaseTheirOwnSubjectEffects() throws Exception {
        var seller = login("ban-seller", "user");
        var buyer = login("ban-buyer", "user");
        var manager = login("ban-manager", "manager");
        var otherManager = login("ban-other-manager", "manager");
        var otherReporter = login("ban-other-reporter", "user");
        long sellerId = seller.account().id();
        long product = publicProduct(seller);
        long active = activeTrade(buyer, seller);
        var pending = post(buyer, "/products/" + product + "/purchase-requests",
                "{\"expected_product_version\":1}", key(), 201).path("id").asLong();
        long initialBanned = bannedAccounts(manager);
        assertThat(get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean(true)).isFalse();
        String ban = """
                {"action":"restrict_account","target_type":"account","target_id":"%d"}
                """.formatted(sellerId);

        long firstCase = claimedCase(buyer, manager, "account", sellerId);
        var first = post(manager, decisionPath(firstCase), decision(ban), key(), 201);
        assertThat(get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean()).isTrue();
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned + 1);
        assertThat(get(seller, "/account/overview", 200).at("/reports/received").asLong()).isEqualTo(1);
        var report = get(seller, "/account/resources?kind=report&direction=received", 200).at("/items/0");
        assertThat(report.path("case_id").asLong()).isEqualTo(firstCase);
        assertThat(report.path("summary").asString()).isEqualTo("收到的事项已作出处理决定");
        assertThat(report.toString()).doesNotContain("核实违规");
        get(buyer, "/products/" + product, 404);
        var ownerProduct = get(seller, "/products/" + product, 200);
        assertThat(ownerProduct.path("lifecycle_state").asString()).isEqualTo("public");
        assertThat(ownerProduct.at("/display_restrictions/0/source_type").asString()).isEqualTo("account_ban");
        assertThat(db.sql("select close_reason from trade where id = ?").param(pending).query(String.class).single())
                .isEqualTo("account_banned");
        assertThat(db.sql("select archived_at is not null from trade_conversation where trade_id = ?")
                .param(pending).query(Boolean.class).single()).isTrue();
        assertThat(activeSources(active)).hasSize(1);

        long secondCase = claimedCase(otherReporter, otherManager, "account", sellerId);
        var second = post(otherManager, decisionPath(secondCase), decision(ban), key(), 201);
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned + 1);
        assertThat(activeSources(active)).hasSize(2);
        lift(manager, firstCase, first);
        assertThat(db.sql("""
                select count(*) from notification where source_type = 'case' and source_id = ?
                  and event_type in ('management.case_decide', 'management.case_execute', 'management.case_lift')
                """).param(firstCase).query(Long.class).single()).isZero();
        assertThat(get(manager, "/cases/" + firstCase, 200).path("archived_at").asText())
                .isNotBlank();
        assertThat(get(otherManager, "/cases/" + secondCase, 200).path("archived_at").isNull())
                .isTrue();
        assertThat(get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean()).isTrue();
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned + 1);
        get(buyer, "/products/" + product, 404);
        assertThat(activeSources(active)).hasSize(1);

        lift(otherManager, secondCase, second);
        assertThat(get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean(true)).isFalse();
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned);
        assertThat(activeSources(active)).isEmpty();
        var publicProduct = get(buyer, "/products/" + product, 200);
        assertThat(publicProduct.has("display_restrictions")).isFalse();
        assertThat(get(seller, "/products/" + product, 200).path("display_restrictions").size()).isZero();
        assertThat(db.sql("select status from trade where id = ?").param(pending).query(String.class).single())
                .isEqualTo("closed");
    }

    @Test
    void bothParticipantsResolvingADisputeArchivesOnlyItsCase() throws Exception {
        var buyer = login("dispute-buyer", "user");
        var seller = login("dispute-seller", "user");
        var manager = login("dispute-manager", "manager");
        long trade = activeTrade(buyer, seller);
        var opened = post(buyer, "/trades/" + trade + "/disputes",
                "{\"statement\":\"请核实交接安排\",\"expected_version\":1}", key(), 201);
        long dispute = opened.at("/dispute/id").asLong();
        long caseId = opened.at("/dispute/case_id").asLong();
        post(manager, "/admin/cases/" + caseId + "/claim", null, key(), 200);
        long otherCase = claimedTradeCase(seller, manager, trade);
        post(manager, "/admin/cases/" + caseId + "/inquiries",
                "{\"peer_account_id\":\"" + buyer.account().id() + "\",\"scope_text\":\"请说明情况\"}", key(), 201);
        String path = "/trades/" + trade + "/disputes/" + dispute + "/resolution-confirmations";
        var first = post(buyer, path, tradeVersion(opened), key(), 200);
        assertThat(first.at("/trade/status").asString()).isEqualTo("disputed");
        assertThat(get(manager, "/cases/" + caseId, 200).path("archived_at").isNull()).isTrue();

        db.sql("delete from trade_dispute_case where case_id = ?").param(caseId).update();
        var rejected = post(seller, path, tradeVersion(first), key(), 409);
        assertThat(rejected.at("/error/code").asString()).isEqualTo("TARGET_STATE_CONFLICT");
        assertThat(db.sql("select status from trade where id = ?").param(trade).query(String.class).single())
                .isEqualTo("disputed");
        db.sql("insert into trade_dispute_case (case_id, dispute_id, trade_id) values (?, ?, ?)")
                .param(caseId).param(dispute).param(trade).update();

        String secondKey = key();
        var resolved = post(seller, path, tradeVersion(first), secondKey, 200);
        assertThat(post(seller, path, tradeVersion(first), secondKey, 200)).isEqualTo(resolved);
        assertThat(resolved.at("/trade/status").asString()).isEqualTo("in_progress");
        assertThat(resolved.at("/dispute/status").asString()).isEqualTo("resolved");
        assertThat(get(manager, "/cases/" + caseId, 200).path("archived_at").isString()).isTrue();
        assertThat(get(manager, "/cases/" + otherCase, 200).path("archived_at").isNull()).isTrue();
        String completedDisputes = "/management/todos?kind=dispute&keyword=" + caseId;
        for (String ownership : List.of("completed_mine", "completed_all")) {
            var completed = get(manager, completedDisputes + "&ownership=" + ownership, 200);
            assertThat(completed.path("items")).anySatisfy(item -> {
                assertThat(item.path("case_id").asLong()).isEqualTo(caseId);
                assertThat(item.path("manager_id").asLong()).isEqualTo(manager.account().id());
                assertThat(item.path("completed_at").isString()).isTrue();
            });
            assertThat(completed.at("/counts_by_kind/dispute").asLong()).isPositive();
        }
        assertThat(db.sql("""
                select actor_kind from moderation_case_action where case_id = ? and action_kind = 'close'
                """).param(caseId).query(String.class).list()).containsExactly("system");
        assertThat(db.sql("select archived_at is not null from case_conversation where case_id = ?")
                .param(caseId).query(Boolean.class).list()).containsExactly(true);
        assertThat(db.sql("select archived_at is null from trade_conversation where trade_id = ?")
                .param(trade).query(Boolean.class).single()).isTrue();
    }

    @Test
    void verifiedEvidenceCanOnlyBeOpenedByTheCurrentClaimant() throws Exception {
        var reporter = login("evidence-reporter", "user");
        var target = login("evidence-target", "user");
        var manager = login("evidence-manager", "manager");
        var otherManager = login("evidence-other", "manager");
        var env = app.getEnvironment();
        var now = Instant.now().minusSeconds(1);
        var location = new OssFileObjects.Location(env.getRequiredProperty("OSS_BUCKET"),
                env.getRequiredProperty("OSS_PREFIX") + "/case_evidence/" + UUID.randomUUID());
        var registry = app.getBean(FileRegistry.class);
        long owner = reporter.account().id();
        long file = registry.register(new UploadRegistration.Draft(owner, FilePurpose.CASE_EVIDENCE, null,
                location, 150, "image/png", "s4-fixture", now, now.plusSeconds(60), now.plusSeconds(300))).fileId();
        registry.markVerified(file, owner, "s4-fixture-etag", new VerifiedContent(150, "image/png"));
        long caseId = post(reporter, "/cases", """
                {"target":{"target_type":"account","target_id":"%d"},"reason":"请核实"}
                """.formatted(target.account().id()), key(), 201).path("case_id").asLong();
        post(reporter, "/cases/" + caseId + "/supplements", """
                {"note":"补充图片说明","attachments":[{"file_id":"%d"}]}
                """.formatted(file), key(), 200);
        long evidence = db.sql("select id from case_evidence where case_id = ? and file_id = ?")
                .param(caseId).param(file).query(Long.class).single();
        String path = "/admin/cases/" + caseId + "/evidence/" + evidence + "/file";
        get(manager, path, 404);
        post(manager, "/admin/cases/" + caseId + "/claim", null, key(), 200);
        get(otherManager, path, 404);
        get(reporter, path, 404);
        var response = http.send(request(manager, path).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as(response.body()).isEqualTo(302);
        assertThat(response.headers().firstValue("Cache-Control")).contains("no-store");
        assertThat(response.headers().firstValue("Referrer-Policy")).contains("no-referrer");
        var redirect = URI.create(response.headers().firstValue("Location").orElseThrow());
        assertThat(redirect.getPath()).endsWith(location.key());
        assertThat(redirect.getRawQuery()).isNotEmpty();
        var pdfLocation = new OssFileObjects.Location(location.bucket(),
                env.getRequiredProperty("OSS_PREFIX") + "/case_evidence/" + UUID.randomUUID());
        long pdfFile = registry.register(new UploadRegistration.Draft(owner, FilePurpose.CASE_EVIDENCE, null,
                pdfLocation, 150, "application/pdf", "s4-fixture", now,
                now.plusSeconds(60), now.plusSeconds(300))).fileId();
        registry.markVerified(pdfFile, owner, "s4-pdf-etag", new VerifiedContent(150, "application/pdf"));
        post(reporter, "/cases/" + caseId + "/supplements", """
                {"attachments":[{"file_id":"%d"}]}
                """.formatted(pdfFile), key(), 200);
        long pdfEvidence = db.sql("select id from case_evidence where case_id = ? and file_id = ?")
                .param(caseId).param(pdfFile).query(Long.class).single();
        String pdfPath = "/cases/" + caseId + "/evidence/" + pdfEvidence + "/file";
        var pdfResponse = http.send(request(reporter, pdfPath).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(pdfResponse.statusCode()).isEqualTo(302);
        assertThat(URI.create(pdfResponse.headers().firstValue("Location").orElseThrow()).getQuery())
                .contains("response-content-disposition=inline")
                .doesNotContain("response-content-type=");
        var ownDetail = get(reporter, "/cases/" + caseId, 200);
        assertThat(ownDetail.at("/report_materials/attachments/0/content_type").asString()).isEqualTo("image/png");
        assertThat(ownDetail.at("/report_materials/attachments/1/content_type").asString()).isEqualTo("application/pdf");
        assertThat(ownDetail.path("reported_reason").asString()).isEqualTo("请核实");
        assertThat(ownDetail.at("/report_materials/supplements/0/note").asString()).isEqualTo("补充图片说明");
        assertThat(ownDetail.at("/report_materials/attachments/0/evidence_id").asLong()).isEqualTo(evidence);
        assertThat(ownDetail.path("thread").isNull()).isTrue();
        assertThat(get(target, "/cases/" + caseId, 404).has("report_materials")).isFalse();
        String ownFile = "/cases/" + caseId + "/evidence/" + evidence + "/file";
        var ownResponse = http.send(request(reporter, ownFile).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(ownResponse.statusCode()).isEqualTo(302);
        assertThat(ownResponse.headers().firstValue("Cache-Control")).contains("no-store");
        get(target, ownFile, 404);
        get(manager, ownFile, 404);
        get(reporter, "/cases/" + caseId + "/evidence/999999999/file", 404);
        var detail = get(manager, "/cases/" + caseId, 200);
        assertThat(detail.has("report_materials")).isFalse();
        assertThat(detail.path("decision_basis_actions").get(0).path("note").asString()).isEqualTo("补充图片说明");
        assertThat(detail.path("evidence").get(0).path("decision_basis").asBoolean()).isTrue();
        post(manager, decisionPath(caseId), """
                {"decision_kind":"no_action","reason":"已核实补充材料","basis_refs":["action:%s","evidence:%d"]}
                """.formatted(detail.path("decision_basis_actions").get(0).path("action_id").asString(), evidence),
                key(), 201);
        db.sql("update account set role = 'user' where account_id = ?").param(manager.account().id()).update();
        get(manager, path, 404);
    }

    @Test
    void unansweredInquiriesAreOnePrivateTodoPerCase() throws Exception {
        var reporter = login("todo-reporter", "user");
        var recipient = login("todo-recipient", "user");
        var manager = login("todo-manager", "manager");
        long caseId = claimedCase(reporter, manager, "account", recipient.account().id());
        String inquiryPath = "/admin/cases/" + caseId + "/inquiries";
        String sides = "\"peer_account_id\":\"" + recipient.account().id() + "\"";
        var first = post(manager, inquiryPath, "{" + sides + ",\"scope_text\":\"第一项\"}", key(), 201);
        var second = post(manager, inquiryPath, "{" + sides + ",\"scope_text\":\"第二项\"}", key(), 201);
        String todos = "/account/todos?kind=inquiry_response&page_size=1";
        var page = get(recipient, todos, 200);
        assertThat(page.path("total").asLong()).isEqualTo(1);
        assertThat(page.at("/counts_by_kind/inquiry_response").asLong()).isEqualTo(1);
        assertThat(page.at("/items/0/source/case_id").asLong()).isEqualTo(caseId);
        assertThat(page.at("/items/0/source/inquiry_action_ids").valueStream().map(JsonNode::asString).toList())
                .containsExactly(first.path("inquiry_action_id").asString(), second.path("inquiry_action_id").asString());
        assertThat(get(reporter, todos, 200).path("total").asLong()).isZero();
        assertThat(get(recipient, "/account/overview", 200).path("todo_count").asLong()).isEqualTo(1);
        assertThat(get(recipient, "/account/overview", 200).at("/reports/received").asLong()).isZero();
        var statement = post(recipient, "/cases/" + caseId + "/messages", """
                {"thread":%s,"message_kind":"statement","body":"说明第一项","inquiry_action_id":"%s"}
                """.formatted(first.path("thread"), first.path("inquiry_action_id").asString()), key(), 201);
        assertThat(get(recipient, todos, 200).at("/items/0/source/inquiry_action_ids")
                .valueStream().map(JsonNode::asString).toList()).containsExactly(second.path("inquiry_action_id").asString());
        long branch = statement.at("/thread/conversation_id").asLong();
        long message = statement.path("case_message_id").asLong();
        assertThat(db.sql("""
                select recipient_account_id from user_event
                where event_type = 'message_created' and source_type = 'case_conversation'
                  and source_id = ? and payload_id = ?
                """).param(branch).param(message).query(Long.class).list()).containsExactlyInAnyOrder(
                        recipient.account().id(), manager.account().id());
        var otherManager = login("todo-other-manager", "manager");
        String read = "/conversations/case/" + branch + "/read-progress";
        String atSeq = "{\"displayed_seq\":" + statement.path("seq").asLong() + "}";
        post(otherManager, read, atSeq, key(), 404);
        post(manager, read, atSeq, key(), 200);
        assertThat(db.sql("""
                select recipient_account_id from user_event
                where event_type = 'message_read' and source_type = 'case_conversation' and source_id = ?
                """).param(branch).query(Long.class).list()).containsExactly(manager.account().id());
    }

    private static String tradeVersion(JsonNode response) {
        return "{\"expected_version\":" + response.at("/trade/version").asInt() + "}";
    }

    private static long bannedAccounts(SessionService.Issued manager) throws Exception {
        return get(manager, "/management/statistics?time_scope=all", 200).at("/accounts/banned").asLong();
    }

    private static JsonNode lift(SessionService.Issued manager, long caseId, JsonNode decision) throws Exception {
        String id = decision.at("/enforcements/0/enforcement_id").asString();
        return post(manager, "/admin/cases/" + caseId + "/enforcements/" + id + "/lift",
                "{\"reason\":\"已复核\"}", key(), 200);
    }

    private static SessionService.Issued login(String name, String role) {
        String email = name + "-" + RUN + "@example.invalid";
        String hash = app.getBean(PasswordHasher.class).hash(PASSWORD);
        db.sql("insert into account (email, display_name, password_hash, role) values (?, ?, ?, ?)")
                .param(email).param(name).param(hash).param(role).update();
        var session = app.getBean(AccountService.class).login(email, PASSWORD);
        SESSIONS.add(session);
        return session;
    }

    private static long activeTrade(SessionService.Issued buyer, SessionService.Issued seller) {
        long product = publicProduct(seller);
        long trade = db.sql("""
                insert into trade (product_id, buyer_id, seller_id, status, requested_at, responded_at, created_at, updated_at)
                values (?, ?, ?, 'in_progress', now(), now(), now(), now()) returning id
                """).param(product).param(buyer.account().id()).param(seller.account().id()).query(Long.class).single();
        db.sql("update product set lifecycle_state = 'in_trade', occupied_by_trade_id = ? where product_id = ?")
                .param(trade).param(product).update();
        db.sql("insert into trade_conversation (trade_id, created_at) values (?, now())").param(trade).update();
        return trade;
    }

    private static long effectiveAgreement(long trade, long buyerId) {
        long agreement = db.sql("""
                insert into agreement_version
                    (trade_id, version_no, status, proposed_by, delivery_at, delivery_place_text,
                     delivery_method, amount_cents, payment_method, payment_timing, proposed_at,
                     business_event_id)
                values (?, 1, 'effective', ?, now(), 'fixture place', 'face_to_face', 100,
                        'offline', 'on_delivery', now(), gen_random_uuid())
                returning id
                """).param(trade).param(buyerId).query(Long.class).single();
        db.sql("update trade set status = 'in_progress', active_agreement_id = ? where id = ?")
                .param(agreement).param(trade).update();
        return agreement;
    }

    private static long publicProduct(SessionService.Issued seller) {
        return db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, 'Trade fixture', 'Trade fixture', 100, 'public') returning product_id
                """).param(seller.account().id()).query(Long.class).single();
    }

    private static long claimedTradeCase(SessionService.Issued reporter, SessionService.Issued manager, long trade)
            throws Exception {
        return claimedCase(reporter, manager, "trade", trade);
    }

    private static long claimedCase(SessionService.Issued reporter, SessionService.Issued manager, String type, long id)
            throws Exception {
        var report = """
                {"target":{"target_type":"%s","target_id":"%d"},"reason":"请核实"}
                """.formatted(type, id);
        long caseId = Long.parseLong(post(reporter, "/cases", report, key(), 201).path("case_id").asString());
        post(manager, "/admin/cases/" + caseId + "/claim", null, key(), 200);
        return caseId;
    }

    private static String decisionPath(long caseId) {
        return "/admin/cases/" + caseId + "/decisions";
    }

    private static String decision(String instructions) {
        return """
                {"decision_kind":"violation","reason":"核实违规","basis_refs":[],"enforcements":[%s]}
                """.formatted(instructions);
    }

    private static String noAction(String instructions) {
        return """
                {"decision_kind":"no_action","reason":"核实后无需处置","basis_refs":[],"enforcements":[%s]}
                """.formatted(instructions);
    }

    private static String freeze(long trade) {
        return """
                {"action":"freeze_trade","target_type":"trade","target_id":"%s"}
                """.formatted(trade);
    }

    private static String lift(long trade) {
        return """
                {"action":"lift_trade_freeze","target_type":"trade","target_id":"%s"}
                """.formatted(trade);
    }

    private static List<Long> activeSources(long trade) {
        return db.sql("select source_ref from trade_freeze where trade_id = ? and ended_at is null")
                .param(trade).query(Long.class).list();
    }

    private static HttpResponse<String> requestPasswordReset(String email) throws Exception {
        var entry = http.send(HttpRequest.newBuilder(URI.create(baseUrl + "/account/entry-context")).GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(entry.statusCode()).isEqualTo(200);
        var cookie = entry.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0];
        var csrf = json.readTree(entry.body()).path("csrf_token").asString();
        var body = json.createObjectNode().put("purpose", "password_reset").put("email", email);
        return http.send(HttpRequest.newBuilder(URI.create(baseUrl + "/account/email-verifications"))
                .header("Origin", ORIGIN).header("Cookie", cookie).header("X-CSRF-Token", csrf)
                .header("Idempotency-Key", key()).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString())).build(), HttpResponse.BodyHandlers.ofString());
    }

    private static JsonNode post(SessionService.Issued session, String path, String body, String key, int status)
            throws Exception {
        return send(request(session, path)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.csrfToken())
                .header("Idempotency-Key", key)
                .header("Content-Type", "application/json")
                .POST(body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body))
                .build(), status);
    }

    private static JsonNode get(SessionService.Issued session, String path, int status) throws Exception {
        return send(request(session, path).GET().build(), status);
    }

    private static HttpRequest.Builder request(SessionService.Issued session, String path) {
        return HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(10))
                .header("Cookie", AccountCookies.SESSION + "=" + session.token());
    }

    private static JsonNode send(HttpRequest request, int status) throws Exception {
        var response = http.send(request, HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as("%s %s: %s", request.method(), request.uri().getPath(), response.body())
                .isEqualTo(status);
        return json.readTree(response.body());
    }

    private static String key() {
        return UUID.randomUUID().toString();
    }
}
