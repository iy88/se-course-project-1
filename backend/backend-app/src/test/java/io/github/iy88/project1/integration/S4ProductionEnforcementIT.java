package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.AccountCookies;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
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
        long product = db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, 'Trade fixture', 'Trade fixture', 100, 'public') returning product_id
                """).param(seller.account().id()).query(Long.class).single();
        long trade = db.sql("""
                insert into trade (product_id, buyer_id, seller_id, status, requested_at, responded_at, created_at, updated_at)
                values (?, ?, ?, 'in_progress', now(), now(), now(), now()) returning id
                """).param(product).param(buyer.account().id()).param(seller.account().id()).query(Long.class).single();
        db.sql("update product set lifecycle_state = 'in_trade', occupied_by_trade_id = ? where product_id = ?")
                .param(trade).param(product).update();
        db.sql("insert into trade_conversation (trade_id, created_at) values (?, now())").param(trade).update();
        return trade;
    }

    private static long claimedTradeCase(SessionService.Issued reporter, SessionService.Issued manager, long trade)
            throws Exception {
        var report = """
                {"target":{"target_type":"trade","target_id":"%s"},"reason":"交易需核实"}
                """.formatted(trade);
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

    private static JsonNode post(SessionService.Issued session, String path, String body, String key, int status)
            throws Exception {
        var request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(10))
                .header("Cookie", AccountCookies.SESSION + "=" + session.token())
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.csrfToken())
                .header("Idempotency-Key", key)
                .header("Content-Type", "application/json")
                .POST(body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body));
        var response = http.send(request.build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as("POST %s: %s", path, response.body()).isEqualTo(status);
        return json.readTree(response.body());
    }

    private static String key() {
        return UUID.randomUUID().toString();
    }
}
