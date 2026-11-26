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
        var freeze = post(manager, decisionPath(first), decision(first, freeze(trade)), key(), 201);
        String enforcement = freeze.at("/enforcements/0/enforcement_id").asString();
        assertThat(freeze.at("/enforcements/0/result_ref").asString()).startsWith("trade_transition:");
        db.sql("update case_enforcement set result_type = 'trade', result_id = ? where case_id = ? and enforcement_id = ?")
                .param(trade).param(first).param(enforcement).update();
        long second = claimedTradeCase(seller, otherManager, trade);
        var secondFreeze = post(otherManager, decisionPath(second), decision(second, freeze(trade)), key(), 201);
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
    void decisionAcquiresTheCombinedLockPlanAndCommitsBothTradeActions() throws Exception {
        var buyer = login("batch-buyer", "user");
        var seller = login("batch-seller", "user");
        var manager = login("batch-manager", "manager");
        long trade = activeTrade(buyer, seller);
        long caseId = claimedTradeCase(buyer, manager, trade);
        var terminate = """
                {"action":"adjust_trade_status","target_type":"trade","target_id":"%s","expected_result":"terminated"}
                """.formatted(trade);
        var response = post(manager, decisionPath(caseId), decision(caseId, freeze(trade) + "," + terminate),
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
                {"action":"adjust_trade_status","target_type":"trade","target_id":"%d","expected_result":"rejected"}
                """.formatted(trade);
        var rejected = post(manager, decisionPath(caseId), decision(caseId, freeze(trade) + "," + invalid),
                key(), 409);
        assertThat(rejected.at("/error/code").asString()).isEqualTo("TRANSITION_NOT_ALLOWED");
        assertThat(activeSources(trade)).isEmpty();
        assertThat(db.sql("select case_status from moderation_case where id = ?").param(caseId)
                .query(String.class).single()).isEqualTo("claimed");
        assertThat(db.sql("select count(*) from case_enforcement where case_id = ?").param(caseId)
                .query(Long.class).single()).isZero();
        assertThat(db.sql("select count(*) from notification where source_type = 'case' and source_id = ?")
                .param(caseId).query(Long.class).single()).isZero();
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
        String ban = """
                {"action":"restrict_account","target_type":"account","target_id":"%d"}
                """.formatted(sellerId);

        long firstCase = claimedCase(buyer, manager, "account", sellerId);
        var first = post(manager, decisionPath(firstCase), decision(firstCase, ban), key(), 201);
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned + 1);
        assertThat(get(seller, "/account/overview", 200).at("/reports/received").asLong()).isEqualTo(1);
        var report = get(seller, "/account/resources?kind=report&direction=received", 200).at("/items/0");
        assertThat(report.path("case_id").asLong()).isEqualTo(firstCase);
        assertThat(report.path("summary").asString()).isEqualTo("收到的事项已作出处理决定");
        assertThat(report.toString()).doesNotContain("核实违规");
        get(buyer, "/products/" + product, 404);
        assertThat(get(seller, "/products/" + product, 200).path("lifecycle_state").asString()).isEqualTo("public");
        assertThat(db.sql("select close_reason from trade where id = ?").param(pending).query(String.class).single())
                .isEqualTo("account_banned");
        assertThat(db.sql("select archived_at is not null from trade_conversation where trade_id = ?")
                .param(pending).query(Boolean.class).single()).isTrue();
        assertThat(activeSources(active)).hasSize(1);

        long secondCase = claimedCase(otherReporter, otherManager, "account", sellerId);
        var second = post(otherManager, decisionPath(secondCase), decision(secondCase, ban), key(), 201);
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned + 1);
        assertThat(activeSources(active)).hasSize(2);
        lift(manager, firstCase, first);
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned + 1);
        get(buyer, "/products/" + product, 404);
        assertThat(activeSources(active)).hasSize(1);

        lift(otherManager, secondCase, second);
        assertThat(bannedAccounts(manager)).isEqualTo(initialBanned);
        assertThat(activeSources(active)).isEmpty();
        get(buyer, "/products/" + product, 200);
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
                {"target":{"target_type":"account","target_id":"%d"},"reason":"请核实",
                 "attachments":[{"file_id":"%d"}]}
                """.formatted(target.account().id(), file), key(), 201).path("case_id").asLong();
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
        post(recipient, "/cases/" + caseId + "/messages", """
                {"thread":%s,"message_kind":"statement","body":"说明第一项","inquiry_action_id":"%s"}
                """.formatted(first.path("thread"), first.path("inquiry_action_id").asString()), key(), 201);
        assertThat(get(recipient, todos, 200).at("/items/0/source/inquiry_action_ids")
                .valueStream().map(JsonNode::asString).toList()).containsExactly(second.path("inquiry_action_id").asString());
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

    private static String decision(long caseId, String instructions) {
        return """
                {"decision_kind":"violation","reason":"核实违规","basis_refs":["case:%d"],"enforcements":[%s]}
                """.formatted(caseId, instructions);
    }

    private static String freeze(long trade) {
        return """
                {"action":"freeze_trade","target_type":"trade","target_id":"%s"}
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
