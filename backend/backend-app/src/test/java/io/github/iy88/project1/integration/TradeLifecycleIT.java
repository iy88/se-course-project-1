package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.api.CsrfGuard;
import io.github.iy88.project1.api.trade.TradeActorResolver;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.casemanagement.persistence.TradeTimeoutCases;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.messaging.TaskWorker;
import io.github.iy88.project1.notification.application.NotificationQueries;
import io.github.iy88.project1.notification.application.NotificationQuery;
import io.github.iy88.project1.notification.application.NotificationView;
import io.github.iy88.project1.trade.application.TradeApplication;
import io.github.iy88.project1.trade.application.TradeCommands;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BiConsumer;
import java.util.function.Function;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.web.server.context.WebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

class TradeLifecycleIT {
    private static final UUID RUN = UUID.randomUUID();
    private static final UUID SESSION = UUID.randomUUID();
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final long SELLER = (1L << 46) + (RUN.getLeastSignificantBits() & ((1L << 45) - 1));
    private static final long BUYER_ONE = SELLER + 1_000;
    private static final long BUYER_TWO = SELLER + 2_000;
    private static final long MANAGER = SELLER + 3_000;
    private static final Instant START = Instant.parse("2026-11-20T00:00:00Z");
    private static final AtomicLong PRODUCT_SEQUENCE = new AtomicLong();

    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static TradeApplication trades;
    private static MutableClock clock;
    private static FixturePorts ports;
    private static JsonMapper json;

    @BeforeAll
    static void start() throws IOException {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("REDIS_NAMESPACE", properties.getProperty("REDIS_NAMESPACE") + ":trade:" + RUN);
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        var application = new SpringApplication(BackendAppApplication.class, Fixtures.class,
                BusinessRealtimeIT.Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("trade-integration", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        trades = app.getBean(TradeApplication.class);
        clock = app.getBean(MutableClock.class);
        ports = app.getBean(FixturePorts.class);
        json = app.getBean(JsonMapper.class);
    }

    @AfterAll
    static void stop() {
        if (app == null) {
            return;
        }
        try {
            clean();
        } finally {
            app.close();
        }
    }

    @BeforeEach
    void resetFixtures() {
        clean();
        clock.set(START);
        ports.reset();
    }

    @Test
    void concurrentAcceptKeepsOneOccupancyAndClosesTheLoser() throws Exception {
        long product = product(SELLER);
        long first = create(product, BUYER_ONE);
        long second = create(product, BUYER_TWO);
        var ready = new CyclicBarrier(3);
        var start = new CountDownLatch(1);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var one = executor.submit(() -> acceptResult(ready, start, first));
            var two = executor.submit(() -> acceptResult(ready, start, second));
            ready.await(5, TimeUnit.SECONDS);
            start.countDown();
            var results = List.of(one.get(15, TimeUnit.SECONDS), two.get(15, TimeUnit.SECONDS));
            assertThat(results.stream().filter(Result::ok).count()).isEqualTo(1);
            var loser = results.stream().filter(result -> !result.ok()).findFirst().orElseThrow();
            assertThat(loser.error()).isEqualTo("REQUEST_ALREADY_ENDED");
        }
        var rows = db.sql("SELECT id, status FROM trade WHERE product_id = ? ORDER BY id")
                .param(product).query((row, index) -> new TradeRow(row.getLong("id"),
                        row.getString("status"))).list();
        assertThat(rows).extracting(TradeRow::status)
                .containsExactlyInAnyOrder("in_progress", "closed");
        assertThat(db.sql("SELECT count(*) FROM trade_item_snapshot WHERE product_id = ?").param(product)
                .query(Long.class).single()).isEqualTo(1);
        long winner = rows.stream().filter(row -> "in_progress".equals(row.status()))
                .findFirst().orElseThrow().id();
        long loser = rows.stream().filter(row -> "closed".equals(row.status())).findFirst().orElseThrow().id();
        assertThat(ports.occupancy(product)).isEqualTo(winner);
        assertThat(ports.archived(loser)).isTrue();
        assertThat(db.sql("SELECT close_reason FROM trade WHERE status = 'closed' AND product_id = ?")
                .param(product).query(String.class).single()).isEqualTo("other_user_locked");
        assertThat(db.sql("SELECT count(*) FROM trade_state_history WHERE trade_id = ?")
                .param(winner).query(Long.class).single()).isGreaterThanOrEqualTo(2);
    }

    @Test
    void replayUsesTheSavedResultAndRejectsADifferentPayload() {
        long product = product(SELLER);
        String key = "replay-" + RUN;
        var command = new TradeCommands.CreatePurchaseRequest(product, "hello", 7);
        var first = trades.createPurchaseRequest(account(BUYER_ONE), key, command);
        var replay = trades.createPurchaseRequest(account(BUYER_ONE), key, command);
        assertThat(first.replayed()).isFalse();
        assertThat(replay.replayed()).isTrue();
        assertThat(replay.operationId()).isEqualTo(first.operationId());
        assertThat(replay.data().path("id").stringValue())
                .isEqualTo(first.data().path("id").stringValue());
        assertThatThrownBy(() -> trades.createPurchaseRequest(account(BUYER_ONE), key,
                new TradeCommands.CreatePurchaseRequest(product, "different", 7)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("IDEMPOTENCY_PAYLOAD_CONFLICT"));
        assertThat(db.sql("SELECT count(*) FROM trade WHERE buyer_id = ? AND product_id = ?").param(BUYER_ONE).param(product)
                .query(Long.class).single()).isEqualTo(1);
        long tradeId = Long.parseLong(first.data().path("id").stringValue());
        assertThat(db.sql("SELECT count(*) FROM trade_state_history WHERE trade_id = ?")
                .param(tradeId).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("SELECT count(*) FROM user_event WHERE source_type = 'trade' AND source_id = ?")
                .param(tradeId).query(Long.class).single()).isEqualTo(1);
        assertThat(ports.messages.stream().filter(message -> "request_created".equals(message.type())).count())
                .isEqualTo(1);
        assertThatThrownBy(() -> trades.accept(account(SELLER), "stale-" + RUN,
                new TradeCommands.Versioned(tradeId, 99)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("VERSION_CONFLICT"));
        assertThat(db.sql("SELECT status FROM trade WHERE id = ?").param(tradeId)
                .query(String.class).single()).isEqualTo("pending_acceptance");
    }

    @Test
    void tradeNoticesKeepTheirOwnEventAfterTheTradeAdvances() {
        ports.notifications = app.getBean("tradeNotifications", TradePorts.Notifications.class);
        long product = product(SELLER);
        var created = trades.createPurchaseRequest(account(BUYER_ONE), "notice-create-" + RUN,
                new TradeCommands.CreatePurchaseRequest(product, "可以在图书馆取吗？", 7));
        long tradeId = Long.parseLong(created.data().path("id").stringValue());
        var accepted = trades.accept(account(SELLER), "notice-accept-" + RUN,
                new TradeCommands.Versioned(tradeId, 1));
        trades.proposeAgreement(account(SELLER), "notice-agreement-" + RUN,
                agreement(tradeId, null, accepted.data().path("version").asInt(), 9000));

        var queries = app.getBean(NotificationQueries.class);
        var sellerNotice = queries.list(account(SELLER), NotificationQuery.firstPage()).items().getFirst();
        assertThat(sellerNotice.summary()).isEqualTo("收到购买请求");
        assertThat(queries.get(account(SELLER), sellerNotice.notificationId()).body())
                .contains("可以在图书馆取吗？");

        var buyerNotices = queries.list(account(BUYER_ONE), NotificationQuery.firstPage()).items();
        assertThat(buyerNotices).extracting(NotificationView::summary)
                .containsExactlyInAnyOrder("购买请求已接受", "收到交易约定");
        assertThat(buyerNotices).allSatisfy(notice -> {
            assertThat(notice.subject()).isEqualTo(accepted.data().at("/product/title").stringValue());
            assertThat(notice.source()).isEqualTo(new ResourceRef("trade", tradeId));
            assertThat(notice.readAt()).isNull();
        });
        assertThat(buyerNotices).anySatisfy(notice ->
                assertThat(notice.body()).contains("时间、地点、交付和付款方式"));
        assertThatThrownBy(() -> queries.get(account(BUYER_TWO), sellerNotice.notificationId()))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));
    }

    @Test
    void myTradesUsesTheSameRoleAndStatusFiltersForPageAndTotal() {
        long withdrawn = create(product(SELLER), BUYER_ONE);
        trades.withdraw(account(BUYER_ONE), "list-withdraw-" + RUN, new TradeCommands.Versioned(withdrawn, 1));
        long outgoing = create(product(SELLER), BUYER_ONE);
        long incoming = create(product(BUYER_ONE), BUYER_TWO);
        create(product(SELLER), BUYER_TWO);

        var viewer = account(BUYER_ONE);
        var statuses = List.of("pending_acceptance", "withdrawn");
        var first = trades.listMine(viewer, "all", statuses, 1, 2);
        assertThat(first.path("total").asLong()).isEqualTo(3);
        assertThat(first.path("items").size()).isEqualTo(2);
        assertThat(first.at("/items/0/id").stringValue()).isEqualTo(Long.toString(incoming));
        assertThat(first.at("/items/1/id").stringValue()).isEqualTo(Long.toString(outgoing));

        var second = trades.listMine(viewer, "all", statuses, 2, 2);
        assertThat(second.path("total").asLong()).isEqualTo(3);
        assertThat(second.path("items").size()).isEqualTo(1);
        assertThat(second.at("/items/0/id").stringValue()).isEqualTo(Long.toString(withdrawn));
        assertThat(trades.listMine(viewer, "buyer", List.of("pending_acceptance"), 1, 20).path("total").asLong())
                .isEqualTo(1);
        assertThat(trades.listMine(viewer, "seller", List.of(), 1, 20).at("/items/0/id").stringValue())
                .isEqualTo(Long.toString(incoming));

        var distant = trades.listMine(viewer, "all", List.of(), Integer.MAX_VALUE, 2);
        assertThat(distant.path("items").size()).isZero();
        assertThat(distant.path("total").asLong()).isEqualTo(3);

        var history = trades.getTrade(viewer, withdrawn, List.of("state_history")).path("state_history");
        assertThat(history.size()).isEqualTo(2);
        assertThat(history.get(0).path("action").stringValue()).isEqualTo("request.create");
        assertThat(history.get(1).path("to_status").stringValue()).isEqualTo("withdrawn");
        assertThat(history.get(1).path("actor_id").stringValue()).isEqualTo(Long.toString(BUYER_ONE));
    }

    @Test
    void changeAgreementInvalidatesConfirmationAndSecondConfirmationCompletes() {
        long product = product(SELLER);
        long tradeId = create(product, BUYER_ONE);
        var accepted = trades.accept(account(SELLER), "accept-" + RUN,
                new TradeCommands.Versioned(tradeId, 1));
        int version = accepted.data().path("version").asInt();
        var proposed = trades.proposeAgreement(account(BUYER_ONE), "agreement-" + RUN,
                agreement(tradeId, null, version, 9000));
        long agreementId = Long.parseLong(proposed.data().path("agreement").path("id").stringValue());
        version = proposed.data().path("trade").path("version").asInt();
        var decided = trades.decideAgreement(account(SELLER), "agree-" + RUN,
                new TradeCommands.DecideAgreement(tradeId, agreementId, "accept", version));
        version = decided.data().path("trade").path("version").asInt();
        var confirmed = trades.submitConfirmation(account(BUYER_ONE), "confirm-one-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, "done", version));
        version = confirmed.data().path("trade").path("version").asInt();
        assertThat(db.sql("SELECT active_since IS NOT NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();

        var change = trades.proposeAgreement(account(BUYER_ONE), "change-" + RUN,
                agreement(tradeId, agreementId, version, 8000));
        long changeId = Long.parseLong(change.data().path("agreement").path("id").stringValue());
        version = change.data().path("trade").path("version").asInt();
        String decideChangeKey = "change-agree-" + RUN;
        var decideChange = new TradeCommands.DecideAgreement(tradeId, changeId, "accept", version);
        ports.failAppend = true;
        assertThatThrownBy(() -> trades.decideAgreement(account(SELLER), decideChangeKey, decideChange))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TEST_CONVERSATION_FAILURE"));
        ports.failAppend = false;
        assertThat(db.sql("SELECT count(*) FROM agreement_decision WHERE agreement_id = ?")
                .param(changeId).query(Long.class).single()).isZero();
        assertThat(db.sql("SELECT status FROM agreement_version WHERE id = ?").param(agreementId)
                .query(String.class).single()).isEqualTo("effective");
        assertThat(db.sql("SELECT status FROM agreement_version WHERE id = ?").param(changeId)
                .query(String.class).single()).isEqualTo("proposed");

        var changed = trades.decideAgreement(account(SELLER), decideChangeKey, decideChange);
        assertThat(changed.replayed()).isFalse();
        version = changed.data().path("trade").path("version").asInt();
        assertThat(db.sql("SELECT count(*) FROM trade_confirmation WHERE trade_id = ? AND invalidated_at IS NOT NULL")
                .param(tradeId).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("SELECT ended_at IS NOT NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();

        var firstAgain = trades.submitConfirmation(account(BUYER_ONE), "confirm-two-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, version));
        version = firstAgain.data().path("trade").path("version").asInt();
        var completed = trades.submitConfirmation(account(SELLER), "confirm-three-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, version));
        assertThat(completed.data().path("trade").path("status").stringValue()).isEqualTo("completed");
        assertThat(completed.data().path("trade").path("terminal_reason").stringValue()).isEqualTo("completed");
        assertThat(ports.occupancy(product)).isNull();
        assertThat(ports.archived(tradeId)).isTrue();
        assertThat(completed.data().path("trade").path("product").path("price_cents").asLong()).isEqualTo(10000);
        var eligibility = trades.reviewEligibility(tradeId, BUYER_ONE);
        assertThat(eligibility.eligible()).isTrue();
        assertThat(eligibility.revieweeId()).isEqualTo(SELLER);
        assertThat(trades.reviewEligibility(tradeId, MANAGER).eligible()).isFalse();
        assertThat(trades.conversationAccess(tradeId).buyerId()).isEqualTo(BUYER_ONE);
        assertThat(trades.conversationAccess(tradeId).contains(SELLER)).isTrue();

        int completedVersion = completed.data().path("trade").path("version").asInt();
        var reviewCommand = new TradeCommands.SubmitReview(tradeId, 5, "  很满意  ");
        String buyerReviewKey = "review-buyer-" + RUN;
        var buyerReview = trades.submitReview(account(BUYER_ONE), buyerReviewKey, reviewCommand);
        assertThat(buyerReview.status()).isEqualTo(201);
        assertThat(buyerReview.replayed()).isFalse();
        var reviewNode = buyerReview.data().path("review");
        String reviewId = reviewNode.path("review_id").stringValue();
        assertThat(reviewId).isNotBlank();
        assertThat(reviewNode.path("trade_id").stringValue()).isEqualTo(Long.toString(tradeId));
        assertThat(reviewNode.path("reviewer").path("id").stringValue()).isEqualTo(Long.toString(BUYER_ONE));
        assertThat(reviewNode.path("reviewer").path("display_name").stringValue())
                .isEqualTo("account-" + BUYER_ONE);
        assertThat(reviewNode.path("reviewee").path("id").stringValue()).isEqualTo(Long.toString(SELLER));
        assertThat(reviewNode.path("rating").asInt()).isEqualTo(5);
        assertThat(reviewNode.path("content").stringValue()).isEqualTo("很满意");
        assertThat(reviewNode.path("visible").asBoolean()).isTrue();
        assertThat(reviewNode.path("created_at").stringValue()).isNotBlank();

        var replay = trades.submitReview(account(BUYER_ONE), buyerReviewKey, reviewCommand);
        assertThat(replay.status()).isEqualTo(201);
        assertThat(replay.replayed()).isTrue();
        assertThat(replay.data().path("review").path("review_id").stringValue()).isEqualTo(reviewId);
        assertThatThrownBy(() -> trades.submitReview(account(BUYER_ONE), "review-buyer-other-" + RUN,
                reviewCommand))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("REVIEW_ALREADY_SUBMITTED"));

        var sellerView = trades.getTradeReviews(account(SELLER), tradeId);
        assertThat(sellerView.path("can_review").asBoolean()).isTrue();
        assertThat(sellerView.path("written").isNull()).isTrue();
        assertThat(sellerView.path("received").path("review_id").stringValue()).isEqualTo(reviewId);

        var sellerReview = trades.submitReview(account(SELLER), "review-seller-" + RUN,
                new TradeCommands.SubmitReview(tradeId, 4, "交易顺利"));
        assertThat(sellerReview.status()).isEqualTo(201);
        String sellerReviewId = sellerReview.data().path("review").path("review_id").stringValue();
        var buyerView = trades.getTradeReviews(account(BUYER_ONE), tradeId);
        assertThat(buyerView.path("can_review").asBoolean()).isFalse();
        assertThat(buyerView.path("written").path("review_id").stringValue()).isEqualTo(reviewId);
        assertThat(buyerView.path("received").path("review_id").stringValue()).isEqualTo(sellerReviewId);

        var buyerWritten = trades.listMyReviews(account(BUYER_ONE), "written", 1, 20);
        assertThat(buyerWritten.path("total").asLong()).isEqualTo(1);
        assertThat(buyerWritten.at("/items/0/review_id").stringValue()).isEqualTo(reviewId);
        var buyerReceived = trades.listMyReviews(account(BUYER_ONE), "received", 1, 20);
        assertThat(buyerReceived.path("total").asLong()).isEqualTo(1);
        assertThat(buyerReceived.at("/items/0/review_id").stringValue()).isEqualTo(sellerReviewId);
        var sellerWritten = trades.listMyReviews(account(SELLER), "written", 1, 20);
        assertThat(sellerWritten.path("total").asLong()).isEqualTo(1);
        assertThat(sellerWritten.at("/items/0/review_id").stringValue()).isEqualTo(sellerReviewId);
        assertThat(trades.listMyReviews(account(MANAGER), "written", 1, 20).path("total").asLong()).isZero();
        assertThatThrownBy(() -> trades.getTradeReviews(account(MANAGER), tradeId))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("RESOURCE_NOT_VISIBLE"));

        db.sql("UPDATE trade_review SET visible = FALSE WHERE id = ?").param(Long.parseLong(reviewId)).update();
        var hidden = trades.getTradeReviews(account(SELLER), tradeId).path("received");
        assertThat(hidden.path("visible").asBoolean()).isFalse();
        assertThat(hidden.path("content").isNull()).isTrue();
        assertThat(hidden.path("rating").asInt()).isEqualTo(5);
        assertThat(db.sql("SELECT count(*) FROM trade_review WHERE trade_id = ?").param(tradeId)
                .query(Long.class).single()).isEqualTo(2);
        assertThat(db.sql("SELECT status || ':' || version FROM trade WHERE id = ?").param(tradeId)
                .query(String.class).single()).isEqualTo("completed:" + completedVersion);
    }

    @Test
    void pendingChangeDoesNotBlockCompletionAndTerminalRejectsTheOldProposal() {
        long product = product(SELLER);
        long tradeId = create(product, BUYER_ONE);
        var accepted = trades.accept(account(SELLER), "accept-pending-change-" + RUN,
                new TradeCommands.Versioned(tradeId, 1));
        int version = accepted.data().path("version").asInt();
        var proposed = trades.proposeAgreement(account(BUYER_ONE), "agreement-pending-change-" + RUN,
                agreement(tradeId, null, version, 9000));
        long agreementId = Long.parseLong(proposed.data().path("agreement").path("id").stringValue());
        version = proposed.data().path("trade").path("version").asInt();
        version = trades.decideAgreement(account(SELLER), "agree-pending-change-" + RUN,
                new TradeCommands.DecideAgreement(tradeId, agreementId, "accept", version))
                .data().path("trade").path("version").asInt();
        version = trades.submitConfirmation(account(BUYER_ONE), "confirm-pending-change-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, version))
                .data().path("trade").path("version").asInt();

        var change = trades.proposeAgreement(account(SELLER), "pending-change-" + RUN,
                agreement(tradeId, agreementId, version, 8000));
        long changeId = Long.parseLong(change.data().path("agreement").path("id").stringValue());
        version = change.data().path("trade").path("version").asInt();

        var completed = trades.submitConfirmation(account(SELLER), "confirm-pending-change-two-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, version));
        assertThat(completed.data().path("trade").path("status").stringValue()).isEqualTo("completed");
        assertThat(db.sql("SELECT status FROM agreement_version WHERE id = ?").param(changeId)
                .query(String.class).single()).isEqualTo("proposed");
        assertThat(db.sql("SELECT status FROM agreement_version WHERE id = ?").param(agreementId)
                .query(String.class).single()).isEqualTo("effective");
        int finalVersion = completed.data().path("trade").path("version").asInt();
        assertThatThrownBy(() -> trades.decideAgreement(account(SELLER), "terminal-decision-" + RUN,
                new TradeCommands.DecideAgreement(tradeId, changeId, "accept", finalVersion)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
    }

    @Test
    void caseLiftResolvesTheOriginalTransitionAndRejectsAnOlderFreeze() {
        long tradeId = create(product(SELLER), BUYER_ONE);
        trades.accept(account(SELLER), "accept-case-freeze-" + RUN, new TradeCommands.Versioned(tradeId, 1));
        long caseId = 70_000 + tradeId;
        long otherCase = caseId + 1;
        String basis = "D-case-freeze";
        trades.freeze(account(MANAGER), "initial-case-freeze-" + RUN,
                new TradeCommands.Freeze(caseId, tradeId, basis, "under review"));
        trades.freeze(account(MANAGER), "other-case-freeze-" + RUN,
                new TradeCommands.Freeze(otherCase, tradeId, basis, "another case"));

        var prior = caseWrite("replay-case-freeze", caseId, tradeId, false,
                tx -> trades.freezeLocked(tx, caseId, tradeId, basis, "under review"));
        long originalTransition = prior.transitionId();
        assertThat(prior.alreadyEffective()).isTrue();
        assertThat(prior.frozenBefore()).isFalse();
        assertThat(ports.messageCount(tradeId, "trade_frozen")).isEqualTo(2);

        var lifted = caseWrite("lift-case-freeze", caseId, tradeId, false,
                tx -> trades.liftFreezeLocked(tx, caseId, tradeId, originalTransition, basis, "released"));
        assertThat(lifted.frozenAfter()).isTrue();
        assertThat(db.sql("""
                SELECT original.freeze_id = lifted.freeze_id
                FROM trade_state_history original, trade_state_history lifted
                WHERE original.id = ? AND lifted.id = ? AND lifted.action = 'trade.unfreeze'
                """).param(originalTransition).param(lifted.transitionId())
                .query(Boolean.class).single()).isTrue();

        var next = caseWrite("refreeze-case", caseId, tradeId, false,
                tx -> trades.freezeLocked(tx, caseId, tradeId, basis, "new freeze"));
        assertThat(next.transitionId()).isNotEqualTo(originalTransition);
        assertThatThrownBy(() -> caseWrite("lift-old-case-freeze", caseId, tradeId, false,
                tx -> trades.liftFreezeLocked(tx, caseId, tradeId, originalTransition, basis, "stale release")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TRADE_FREEZE_NOT_ACTIVE"));
        assertThat(db.sql("""
                SELECT source_ref FROM trade_freeze WHERE trade_id = ? AND ended_at IS NULL
                """).param(tradeId).query(Long.class).list()).containsExactlyInAnyOrder(caseId, otherCase);
        assertThat(ports.messageCount(tradeId, "trade_unfrozen")).isZero();
    }

    @Test
    void caseBatchReadsTheTerminalStateWrittenByAnEarlierAction() {
        long tradeId = create(product(SELLER), BUYER_ONE);
        trades.accept(account(SELLER), "accept-case-batch-" + RUN, new TradeCommands.Versioned(tradeId, 1));
        long caseId = 74_000 + tradeId;
        var outcome = caseWrite("case-batch", caseId, tradeId, true, tx -> {
            trades.freezeLocked(tx, caseId, tradeId, "D-batch", "freeze");
            var ended = trades.adjustStatusLocked(tx, caseId, tradeId, "terminated", "D-batch", "terminate");
            assertThatThrownBy(() -> trades.restoreLocked(tx, caseId, tradeId, "D-batch", "restore"))
                    .isInstanceOfSatisfying(BusinessError.class,
                            error -> assertThat(error.code()).isEqualTo("TRADE_TERMINAL"));
            return ended;
        });
        assertThat(outcome.previousStatus()).isEqualTo("in_progress");
        assertThat(outcome.currentStatus()).isEqualTo("terminated");
        assertThat(outcome.frozenBefore()).isTrue();
        assertThat(outcome.frozenAfter()).isFalse();
    }

    @Test
    void freezePausesWaitAndTimeoutFreezesThenGovernanceRestoreDoesNotRestartIt() {
        long product = product(SELLER);
        long tradeId = create(product, BUYER_ONE);
        var accepted = trades.accept(account(SELLER), "accept-freeze-" + RUN,
                new TradeCommands.Versioned(tradeId, 1));
        int version = accepted.data().path("version").asInt();
        var proposed = trades.proposeAgreement(account(BUYER_ONE), "agreement-freeze-" + RUN,
                agreement(tradeId, null, version, 9000));
        long agreementId = Long.parseLong(proposed.data().path("agreement").path("id").stringValue());
        version = proposed.data().path("trade").path("version").asInt();
        version = trades.decideAgreement(account(SELLER), "agree-freeze-" + RUN,
                new TradeCommands.DecideAgreement(tradeId, agreementId, "accept", version))
                .data().path("trade").path("version").asInt();
        trades.submitConfirmation(account(BUYER_ONE), "confirm-freeze-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, version));

        long firstCase = 50_000 + tradeId;
        long secondCase = 55_000 + tradeId;
        trades.freeze(account(MANAGER), "freeze-one-" + RUN,
                new TradeCommands.Freeze(firstCase, tradeId, "D-test-1", "under review"));
        trades.freeze(account(MANAGER), "freeze-two-" + RUN,
                new TradeCommands.Freeze(secondCase, tradeId, "D-test-2", "under review"));
        assertThat(db.sql("SELECT active_since IS NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();
        clock.advance(Duration.ofDays(2));

        var freezeIds = db.sql("SELECT id FROM trade_freeze WHERE trade_id = ? AND ended_at IS NULL ORDER BY id")
                .param(tradeId).query(Long.class).list();
        assertThat(freezeIds).hasSize(2);
        trades.liftFreeze(account(MANAGER), "unfreeze-one-" + RUN,
                new TradeCommands.LiftFreeze(firstCase, tradeId, freezeIds.get(0), "D-test-1", "restored"));
        assertThat(db.sql("SELECT active_since IS NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();
        trades.liftFreeze(account(MANAGER), "unfreeze-two-" + RUN,
                new TradeCommands.LiftFreeze(secondCase, tradeId, freezeIds.get(1), "D-test-2", "restored"));
        assertThat(db.sql("SELECT active_since IS NOT NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();

        clock.advance(Duration.ofDays(7));
        var due = db.sql("""
                SELECT task_id FROM task_schedule WHERE task_kind = 'trade.timeout' AND source_id = ?
                    AND completed_at IS NULL AND cancelled_at IS NULL ORDER BY due_at DESC LIMIT 1
                """).param(tradeId).query(UUID.class).single();
        db.sql("""
                UPDATE task_schedule SET due_at = statement_timestamp(), next_attempt_at = statement_timestamp()
                WHERE task_id = ?
                """).param(due).update();
        assertThat(app.getBean(TaskWorker.class).run(new TaskSchedules.Ready(due, "trade.timeout"))).isTrue();

        assertThat(db.sql("SELECT status FROM trade WHERE id = ?").param(tradeId)
                .query(String.class).single()).isEqualTo("abnormal");
        assertThat(db.sql("SELECT count(*) FROM trade_freeze WHERE trade_id = ? AND source = 'timeout' "
                        + "AND ended_at IS NULL").param(tradeId).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("SELECT end_reason FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(String.class).single()).isEqualTo("timeout");
        assertThat(ports.occupancy(product)).isEqualTo(tradeId);
        assertThat(ports.archived(tradeId)).isFalse();

        long restoreCase = 60_000 + tradeId;
        trades.restore(account(MANAGER), "restore-" + RUN,
                new TradeCommands.Restore(restoreCase, tradeId, "D-restore", "recovered"));
        assertThat(db.sql("SELECT status FROM trade WHERE id = ?").param(tradeId)
                .query(String.class).single()).isEqualTo("in_progress");
        assertThat(db.sql("SELECT end_reason FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(String.class).single()).isEqualTo("timeout");
        long timeoutFreeze = db.sql("""
                SELECT id FROM trade_freeze WHERE trade_id = ? AND source = 'timeout' AND ended_at IS NULL
                """).param(tradeId).query(Long.class).single();
        trades.liftFreeze(account(MANAGER), "unfreeze-timeout-" + RUN,
                new TradeCommands.LiftFreeze(restoreCase, tradeId, timeoutFreeze, "D-restore", "recovered"));
        assertThat(db.sql("SELECT ended_at IS NOT NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();
        assertThat(db.sql("SELECT count(*) FROM trade_confirmation WHERE trade_id = ? AND invalidated_at IS NULL")
                .param(tradeId).query(Long.class).single()).isZero();
        assertThat(ports.occupancy(product)).isEqualTo(tradeId);
        assertThat(ports.archived(tradeId)).isFalse();

        int versionNow = db.sql("SELECT version FROM trade WHERE id = ?").param(tradeId)
                .query(Integer.class).single();
        trades.submitConfirmation(account(BUYER_ONE), "confirm-after-restore-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, versionNow));
        assertThat(db.sql("SELECT active_since IS NOT NULL AND ended_at IS NULL FROM confirmation_wait "
                        + "WHERE trade_id = ?").param(tradeId).query(Boolean.class).single()).isTrue();
        assertThat(db.sql("SELECT wait_seconds FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Integer.class).single()).isEqualTo(604800);
    }

    @Test
    void disputeCreatesOneLinkedDisputeCaseAndReplaysTheSameOperation() {
        long tradeId = create(product(SELLER), BUYER_ONE);
        var accepted = trades.accept(account(SELLER), "accept-dispute-case-" + RUN,
                new TradeCommands.Versioned(tradeId, 1));
        int version = accepted.data().path("version").asInt();
        var command = new TradeCommands.OpenDispute(tradeId, "private delivery detail", version);
        String key = "dispute-case-" + RUN;

        var opened = trades.openDispute(account(BUYER_ONE), key, command);
        assertThat(opened.status()).isEqualTo(201);
        assertThat(opened.replayed()).isFalse();
        assertThat(opened.data().path("trade").path("status").stringValue()).isEqualTo("disputed");
        long disputeId = Long.parseLong(opened.data().path("dispute").path("id").stringValue());
        long caseId = db.sql("SELECT case_id FROM trade_dispute WHERE id = ?").param(disputeId)
                .query(Long.class).single();
        assertThat(caseId).isPositive();
        assertThat(opened.data().path("dispute").path("case_id").stringValue()).isEqualTo(Long.toString(caseId));
        assertThat(trades.getTrade(account(SELLER), tradeId, List.of()).at("/dispute/open/case_id").stringValue())
                .isEqualTo(Long.toString(caseId));
        assertThat(ports.disputeCases.get(disputeId)).isEqualTo(caseId);
        assertThat(db.sql("SELECT case_type FROM moderation_case WHERE id = ?").param(caseId)
                .query(String.class).single()).isEqualTo("dispute");
        assertThat(db.sql("""
                SELECT count(*) FROM trade_dispute_case
                WHERE case_id = ? AND dispute_id = ? AND trade_id = ?
                """).param(caseId).param(disputeId).param(tradeId).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("SELECT count(*) FROM trade_state_history WHERE dispute_id = ? AND case_id = ?")
                .param(disputeId).param(caseId).query(Long.class).single()).isEqualTo(1);

        var replay = trades.openDispute(account(BUYER_ONE), key, command);
        assertThat(replay.status()).isEqualTo(201);
        assertThat(replay.replayed()).isTrue();
        assertThat(replay.data().path("dispute").path("id").stringValue()).isEqualTo(Long.toString(disputeId));
        assertThat(ports.disputeCases).hasSize(1);

        int currentVersion = db.sql("SELECT version FROM trade WHERE id = ?").param(tradeId)
                .query(Integer.class).single();
        assertThatThrownBy(() -> trades.openDispute(account(SELLER), "dispute-case-other-" + RUN,
                new TradeCommands.OpenDispute(tradeId, "another statement", currentVersion)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("DISPUTE_ALREADY_OPEN"));
        assertThat(db.sql("SELECT count(*) FROM trade_dispute WHERE trade_id = ?").param(tradeId)
                .query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("SELECT count(*) FROM trade_dispute_case WHERE trade_id = ?").param(tradeId)
                .query(Long.class).single()).isEqualTo(1);
    }

    @Test
    void disputeResolutionRestoresProgressAndNegotiatedCancellationTerminates() {
        long product = product(SELLER);
        long tradeId = create(product, BUYER_ONE);
        var accepted = trades.accept(account(SELLER), "accept-dispute-" + RUN,
                new TradeCommands.Versioned(tradeId, 1));
        int version = accepted.data().path("version").asInt();
        var proposed = trades.proposeAgreement(account(BUYER_ONE), "agreement-dispute-" + RUN,
                agreement(tradeId, null, version, 9000));
        long agreementId = Long.parseLong(proposed.data().path("agreement").path("id").stringValue());
        version = proposed.data().path("trade").path("version").asInt();
        version = trades.decideAgreement(account(SELLER), "agree-dispute-" + RUN,
                new TradeCommands.DecideAgreement(tradeId, agreementId, "accept", version))
                .data().path("trade").path("version").asInt();
        version = trades.submitConfirmation(account(BUYER_ONE), "confirm-dispute-" + RUN,
                new TradeCommands.ConfirmCompletion(tradeId, null, version))
                .data().path("trade").path("version").asInt();

        var dispute = trades.openDispute(account(SELLER), "dispute-" + RUN,
                new TradeCommands.OpenDispute(tradeId, "not as agreed", version));
        assertThat(dispute.data().path("trade").path("status").stringValue()).isEqualTo("disputed");
        assertThat(db.sql("SELECT end_reason FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(String.class).single()).isEqualTo("disputed");
        assertThat(db.sql("SELECT count(*) FROM trade_confirmation WHERE trade_id = ? AND invalidated_at IS NULL")
                .param(tradeId).query(Long.class).single()).isEqualTo(1);
        long disputeId = Long.parseLong(dispute.data().path("dispute").path("id").stringValue());
        version = dispute.data().path("trade").path("version").asInt();

        var firstResolution = trades.confirmResolution(account(BUYER_ONE), "resolution-one-" + RUN,
                new TradeCommands.ConfirmResolution(tradeId, disputeId, version));
        version = firstResolution.data().path("trade").path("version").asInt();
        var resolved = trades.confirmResolution(account(SELLER), "resolution-two-" + RUN,
                new TradeCommands.ConfirmResolution(tradeId, disputeId, version));
        assertThat(resolved.data().path("trade").path("status").stringValue()).isEqualTo("in_progress");
        assertThat(db.sql("SELECT status FROM trade_dispute WHERE id = ?").param(disputeId)
                .query(String.class).single()).isEqualTo("resolved");
        assertThat(db.sql("SELECT count(*) FROM trade_confirmation WHERE trade_id = ? AND invalidated_at IS NULL")
                .param(tradeId).query(Long.class).single()).isZero();
        assertThat(db.sql("SELECT ended_at IS NOT NULL FROM confirmation_wait WHERE trade_id = ?")
                .param(tradeId).query(Boolean.class).single()).isTrue();
        version = resolved.data().path("trade").path("version").asInt();

        var secondDispute = trades.openDispute(account(SELLER), "dispute-two-" + RUN,
                new TradeCommands.OpenDispute(tradeId, "still not agreed", version));
        long secondDisputeId = Long.parseLong(secondDispute.data().path("dispute").path("id").stringValue());
        version = secondDispute.data().path("trade").path("version").asInt();

        var cancellation = trades.proposeCancellation(account(BUYER_ONE), "cancel-dispute-" + RUN,
                new TradeCommands.ProposeCancellation(tradeId, "agreed to stop", version));
        assertThat(cancellation.data().path("mode").stringValue()).isEqualTo("approval");
        long proposalId = Long.parseLong(cancellation.data().path("proposal").path("id").stringValue());
        version = cancellation.data().path("trade").path("version").asInt();
        var terminated = trades.decideCancellation(account(SELLER), "cancel-accept-" + RUN,
                new TradeCommands.DecideCancellation(tradeId, proposalId, "accept", version));
        assertThat(terminated.data().path("trade").path("status").stringValue()).isEqualTo("terminated");
        assertThat(terminated.data().path("trade").path("terminal_reason").stringValue()).isEqualTo("cancelled");
        assertThat(ports.occupancy(product)).isNull();
        assertThat(ports.archived(tradeId)).isTrue();
        assertThat(db.sql("SELECT status FROM trade_dispute WHERE id = ?").param(secondDisputeId)
                .query(String.class).single()).isEqualTo("terminated");
        assertThat(db.sql("SELECT status FROM trade_dispute WHERE id = ?").param(disputeId)
                .query(String.class).single()).isEqualTo("resolved");
    }

    @Test
    void failedConversationAppendRollsBackTradeHistoryAndIdempotency() {
        long product = product(SELLER);
        ports.failAppend = true;
        String key = "rollback-" + RUN;
        assertThatThrownBy(() -> trades.createPurchaseRequest(account(BUYER_TWO), key,
                new TradeCommands.CreatePurchaseRequest(product, null, 7)))
                .isInstanceOf(BusinessError.class);
        ports.failAppend = false;
        assertThat(db.sql("SELECT count(*) FROM trade WHERE buyer_id = ? AND product_id = ?")
                .param(BUYER_TWO).param(product).query(Long.class).single()).isZero();
        assertThat(db.sql("SELECT count(*) FROM operation_record WHERE actor_id = ? AND idempotency_key = ?")
                .param(Long.toString(BUYER_TWO)).param(key).query(Long.class).single()).isZero();
    }

    @Test
    void failedAcceptanceRollsBackProductWriteAndCanRetryWithTheSameKey() {
        long product = product(SELLER);
        long tradeId = create(product, BUYER_ONE);
        long before = db.sql("SELECT count(*) FROM audit_record WHERE target_type = 'trade' AND target_id = ?")
                .param(tradeId).query(Long.class).single();
        String key = "rollback-accept-" + RUN;
        var command = new TradeCommands.Versioned(tradeId, 1);
        ports.failAppend = true;
        assertThatThrownBy(() -> trades.accept(account(SELLER), key, command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TEST_CONVERSATION_FAILURE"));
        ports.failAppend = false;
        assertThat(ports.occupancy(product)).isNull();
        assertThat(db.sql("SELECT status FROM trade WHERE id = ?").param(tradeId).query(String.class).single())
                .isEqualTo("pending_acceptance");
        assertThat(db.sql("SELECT count(*) FROM trade_item_snapshot WHERE trade_id = ?")
                .param(tradeId).query(Long.class).single()).isZero();
        assertThat(db.sql("SELECT count(*) FROM trade_state_history WHERE trade_id = ?")
                .param(tradeId).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("SELECT count(*) FROM audit_record WHERE target_type = 'trade' AND target_id = ?")
                .param(tradeId).query(Long.class).single()).isEqualTo(before);
        assertThat(trades.accept(account(SELLER), key, command).replayed()).isFalse();
        assertThat(ports.occupancy(product)).isEqualTo(tradeId);
    }

    @Test
    void accountBanClosesPendingAndReleasingOneSourceKeepsOtherFreezes() {
        long activeProduct = product(SELLER);
        long active = create(activeProduct, BUYER_ONE);
        trades.accept(account(SELLER), "account-ban-accept-" + RUN, new TradeCommands.Versioned(active, 1));
        long pending = create(product(SELLER), BUYER_ONE);
        ports.restricted.put(BUYER_ONE, true);

        applyRestriction("first-ban", active, (transaction, plan) ->
                trades.applyAccountBan(transaction, plan, BUYER_ONE, 71, "限制交易", "restriction:71"));
        applyRestriction("second-ban", active, (transaction, plan) ->
                trades.applyAccountBan(transaction, plan, BUYER_ONE, 72, "限制交易", "restriction:72"));

        assertThat(ports.archived(pending)).isTrue();
        assertThat(ports.occupancy(activeProduct)).isEqualTo(active);
        assertThat(trades.getTrade(account(BUYER_ONE), pending, List.of()).at("/request/close_reason").stringValue())
                .isEqualTo("account_banned");
        assertThat(trades.getTrade(account(SELLER), active, List.of()).at("/freeze/items").size()).isEqualTo(2);
        assertThat(trades.pairFrozen(SELLER, BUYER_ONE)).isTrue();
        assertThat(trades.pairFrozen(SELLER, BUYER_TWO)).isFalse();

        applyRestriction("lift-first-ban", active, (transaction, plan) ->
                trades.removeAccountBan(transaction, plan, BUYER_ONE, 71, "restriction:71"));
        assertThat(trades.getTrade(account(SELLER), active, List.of()).at("/freeze/items").size()).isEqualTo(1);
        applyRestriction("lift-last-ban", active, (transaction, plan) ->
                trades.removeAccountBan(transaction, plan, BUYER_ONE, 72, "restriction:72"));
        assertThat(trades.getTrade(account(SELLER), active, List.of()).at("/freeze/active").asBoolean()).isFalse();
        assertThat(trades.pairFrozen(SELLER, BUYER_ONE)).isFalse();
    }

    private static void applyRestriction(String key, long tradeId, BiConsumer<WriteTransaction, LockPlan> change) {
        var context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.SYSTEM,
                "restriction-fixture", null, null, null, "trade-integration");
        app.getBean(WriteExecutor.class).run(context, "trade.test.restriction", key + "-" + RUN, tradeId,
                new WriteExecutor.UseCase<Long, Void>() {
                    @Override
                    public JsonNode digestInput(Long id) {
                        return json.createObjectNode().put("trade_id", id);
                    }

                    @Override
                    public LockPlan prepare(ExecutionContext actor, Long id) {
                        return trades.accountBanPlan(BUYER_ONE).merge(
                                new LockPlan(Map.of(BUYER_ONE, LockPlan.AccountMode.EXCLUSIVE), Set.of()));
                    }

                    @Override
                    public Void qualify(ExecutionContext actor, Long id, LockPlan plan) {
                        return null;
                    }

                    @Override
                    public void requireReplayAccess(ExecutionContext actor, Void qualified, ResourceRef resource) {
                    }

                    @Override
                    public WriteResult.Response<?> write(WriteTransaction transaction, Long id, Void qualified,
                                                         LockPlan plan) {
                        change.accept(transaction, plan);
                        return new WriteResult.Response<>(204, null, new ResourceRef("trade", id));
                    }
                });
    }

    @Test
    void httpEntryUsesTrustedSessionAndReturnsSnakeCaseTradeView() throws Exception {
        long product = product(SELLER);
        int port = ((WebServerApplicationContext) app).getWebServer().getPort();
        var client = HttpClient.newHttpClient();
        String body = "{\"note\":\"http\",\"expected_product_version\":7}";
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port
                        + "/api/v1/products/" + product + "/purchase-requests"))
                .header("Content-Type", "application/json")
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", "it-csrf")
                .header("Idempotency-Key", "http-" + RUN)
                .header("Cookie", "it_account=" + BUYER_ONE)
                .POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var response = client.send(request, HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(201);
        assertThat(response.headers().firstValue("Location")).hasValueSatisfying(location ->
                assertThat(location).startsWith("/api/v1/trades/"));
        var created = json.readTree(response.body());
        assertThat(created.path("status").stringValue()).isEqualTo("pending_acceptance");
        assertThat(created.has("trade_conversation_id")).isTrue();
        long tradeId = Long.parseLong(created.path("id").stringValue());
        var detail = client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port
                                + "/api/v1/trades/" + tradeId))
                        .header("Cookie", "it_account=" + BUYER_ONE).GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(detail.statusCode()).isEqualTo(200);
        var notVisible = client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port
                                + "/api/v1/trades/" + tradeId))
                        .header("Cookie", "it_account=" + BUYER_TWO).GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(notVisible.statusCode()).isEqualTo(404);
    }

    private static TradePorts.CaseEnforcementOutcome caseWrite(
            String key, long caseId, long tradeId, boolean product,
            Function<WriteTransaction, TradePorts.CaseEnforcementOutcome> action) {
        var prepared = trades.prepare(MANAGER, tradeId, caseId, product);
        var outcome = new AtomicReference<TradePorts.CaseEnforcementOutcome>();
        app.getBean(WriteExecutor.class).run(account(MANAGER), "test.case.trade", key + "-" + RUN, tradeId,
                new WriteExecutor.UseCase<Long, Void>() {
                    @Override
                    public JsonNode digestInput(Long id) {
                        return json.valueToTree(id);
                    }

                    @Override
                    public LockPlan prepare(ExecutionContext context, Long id) {
                        return prepared.lockPlan();
                    }

                    @Override
                    public Void qualify(ExecutionContext context, Long id, LockPlan plan) {
                        return null;
                    }

                    @Override
                    public void requireReplayAccess(ExecutionContext context, Void qualification, ResourceRef ref) {
                    }

                    @Override
                    public WriteResult.Response<?> write(WriteTransaction tx, Long id, Void qualification,
                                                         LockPlan plan) {
                        if (prepared.productId() != null) {
                            trades.lockCaseProduct(tx, prepared.productId());
                        }
                        trades.lockTrade(tx, id);
                        tx.lock(new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId)),
                                () -> ports.lockAndValidate(tx, caseId, MANAGER, id, "D-case"));
                        trades.lockConversation(tx, prepared.conversationId());
                        outcome.set(action.apply(tx));
                        return new WriteResult.Response<>(200, Map.of(), new ResourceRef("trade", id));
                    }
                });
        return outcome.get();
    }

    private static Result acceptResult(CyclicBarrier ready, CountDownLatch start, long tradeId) throws Exception {
        ready.await(5, TimeUnit.SECONDS);
        start.await(5, TimeUnit.SECONDS);
        try {
            var result = trades.accept(account(SELLER), "concurrent-" + tradeId,
                    new TradeCommands.Versioned(tradeId, 1));
            return new Result(true, null);
        } catch (BusinessError error) {
            return new Result(false, error.code());
        }
    }

    private record Result(boolean ok, String error) {
    }

    private record TradeRow(long id, String status) {
    }

    private static long product(long seller) {
        long product = 700_000 + PRODUCT_SEQUENCE.incrementAndGet()
                + Math.floorMod(RUN.getLeastSignificantBits(), 100_000);
        ports.products.put(product, new TradePorts.ProductState(product, seller, 7, "on_sale", null,
                "测试商品", "描述", 10000, List.of("数码"), List.of(101L)));
        return product;
    }

    private static long create(long product, long buyer) {
        var result = trades.createPurchaseRequest(account(buyer), "create-" + product + "-" + buyer + "-" + RUN,
                new TradeCommands.CreatePurchaseRequest(product, null, 7));
        return Long.parseLong(result.data().path("id").stringValue());
    }

    private static TradeCommands.ProposeAgreement agreement(long tradeId, Long base, int version, long amount) {
        return new TradeCommands.ProposeAgreement(tradeId, START.plusSeconds(86400), "图书馆", "面交", amount,
                "现金", "交付时", base, version);
    }

    private static ExecutionContext account(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), SESSION, null, 1L, "trade-integration");
    }

    private static void clean() {
        var tradeIds = db.sql("""
                SELECT id FROM trade WHERE buyer_id IN (:a, :b, :c) OR seller_id IN (:a, :b, :c)
                """).param("a", BUYER_ONE).param("b", BUYER_TWO).param("c", SELLER)
                .query(Long.class).list();
        if (tradeIds.isEmpty()) {
            return;
        }
        String in = String.join(",", tradeIds.stream().map(String::valueOf).toList());
        db.sql("DELETE FROM user_event WHERE recipient_account_id IN (?, ?, ?)")
                .param(BUYER_ONE).param(BUYER_TWO).param(SELLER).update();
        db.sql("DELETE FROM notification WHERE recipient_account_id IN (?, ?, ?)")
                .param(BUYER_ONE).param(BUYER_TWO).param(SELLER).update();
        db.sql("DELETE FROM account_event_head WHERE account_id IN (?, ?, ?)")
                .param(BUYER_ONE).param(BUYER_TWO).param(SELLER).update();
        db.sql("DELETE FROM task_schedule WHERE source_type = 'trade' AND source_id IN (" + in + ")").update();
        db.sql("DELETE FROM audit_record WHERE target_type = 'trade' AND target_id IN (" + in + ")").update();
        db.sql("DELETE FROM trade_state_history WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM trade_review WHERE trade_id IN (" + in + ")").update();
        var disputeCaseIds = db.sql("SELECT case_id FROM trade_dispute_case WHERE trade_id IN (" + in + ")")
                .query(Long.class).list();
        db.sql("DELETE FROM trade_dispute_case WHERE trade_id IN (" + in + ")").update();
        if (!disputeCaseIds.isEmpty()) {
            String caseIds = String.join(",", disputeCaseIds.stream().map(String::valueOf).toList());
            db.sql("DELETE FROM moderation_case WHERE id IN (" + caseIds + ")").update();
        }
        db.sql("DELETE FROM dispute_resolution_confirmation WHERE dispute_id IN "
                + "(SELECT id FROM trade_dispute WHERE trade_id IN (" + in + "))").update();
        db.sql("DELETE FROM trade_dispute WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM cancellation_decision WHERE cancellation_id IN "
                + "(SELECT id FROM cancellation_proposal WHERE trade_id IN (" + in + "))").update();
        db.sql("DELETE FROM cancellation_proposal WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM agreement_decision WHERE agreement_id IN "
                + "(SELECT id FROM agreement_version WHERE trade_id IN (" + in + "))").update();
        db.sql("DELETE FROM trade_confirmation WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM confirmation_wait WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM trade_freeze WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM trade_item_snapshot WHERE trade_id IN (" + in + ")").update();
        db.sql("UPDATE trade SET active_agreement_id = NULL WHERE id IN (" + in + ")").update();
        db.sql("DELETE FROM agreement_version WHERE trade_id IN (" + in + ")").update();
        db.sql("DELETE FROM trade WHERE id IN (" + in + ")").update();
        db.sql("DELETE FROM operation_record WHERE resource_type = 'trade' AND resource_id IN (:ids)")
                .param("ids", tradeIds).update();
    }

    static class MutableClock extends Clock {
        private volatile Instant instant = START;

        void set(Instant value) {
            instant = value;
        }

        void advance(Duration duration) {
            instant = instant.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }

    static class FixturePorts implements TradePorts.Product, TradePorts.Accounts, TradePorts.Conversation,
            TradePorts.Cases, TradePorts.Notifications {
        final Map<Long, TradePorts.ProductState> products = new ConcurrentHashMap<>();
        final Map<Long, Boolean> restricted = new ConcurrentHashMap<>();
        final Map<Long, Long> tradeConversations = new ConcurrentHashMap<>();
        final Map<Long, Long> conversationTrades = new ConcurrentHashMap<>();
        final List<Message> messages = new CopyOnWriteArrayList<>();
        final Set<Long> archived = ConcurrentHashMap.newKeySet();
        final Map<Long, Long> disputeCases = new ConcurrentHashMap<>();
        final AtomicLong conversationIds = new AtomicLong(800_000);
        final AtomicInteger timeoutCases = new AtomicInteger(900_000);
        final TradeTimeoutCases caseStore;
        volatile boolean failAppend;
        TradePorts.Notifications notifications;

        FixturePorts(TradeTimeoutCases caseStore) {
            this.caseStore = caseStore;
        }

        void reset() {
            products.clear();
            restricted.clear();
            tradeConversations.clear();
            conversationTrades.clear();
            messages.clear();
            archived.clear();
            disputeCases.clear();
            failAppend = false;
            notifications = null;
        }

        boolean archived(long tradeId) {
            Long conversation = tradeConversations.get(tradeId);
            return conversation != null && archived.contains(conversation);
        }

        @Override
        public Optional<TradePorts.ProductState> read(long productId) {
            return Optional.ofNullable(products.get(productId)).map(this::withProductWrites);
        }

        @Override
        public Optional<TradePorts.ProductSummary> visibleSummary(long productId, long viewerId) {
            return read(productId).filter(state -> "on_sale".equals(state.lifecycleState()))
                    .map(state -> new TradePorts.ProductSummary(state.title(), state.priceCents()));
        }

        @Override
        public TradePorts.ProductState lock(WriteTransaction transaction, long productId) {
            db.sql("SELECT true FROM pg_advisory_xact_lock(?)").param(0x4000_0000_0000_0000L + productId)
                    .query(Boolean.class).single();
            var state = products.get(productId);
            return state == null ? null : withProductWrites(state);
        }

        private TradePorts.ProductState withProductWrites(TradePorts.ProductState state) {
            var writes = lastProductWrite(state.productId());
            boolean released = writes.isPresent() && "fixture.product.release".equals(writes.orElseThrow().action());
            Long holder = released ? null : writes.map(ProductWrite::tradeId).orElse(null);
            return new TradePorts.ProductState(state.productId(), state.sellerId(), state.contentVersion(),
                    released ? "off_shelf" : state.lifecycleState(), holder, state.title(), state.description(),
                    state.priceCents(), state.categoryNames(), state.imageFileIds());
        }

        Long occupancy(long productId) {
            return read(productId).orElseThrow().occupancyTradeId();
        }

        private Optional<ProductWrite> lastProductWrite(long productId) {
            return db.sql("""
                    SELECT action, target_id FROM audit_record
                    WHERE target_type = 'trade' AND action IN ('fixture.product.acquire', 'fixture.product.release')
                        AND facts ->> 'product_id' = ?
                    ORDER BY audit_id DESC LIMIT 1
                    """).param(Long.toString(productId))
                    .query((row, index) -> new ProductWrite(row.getString(1), row.getLong(2))).optional();
        }

        private record ProductWrite(String action, long tradeId) {}

        @Override
        public void requireTradable(TradePorts.ProductState state, long buyerId) {
            if (!"on_sale".equals(state.lifecycleState()) || state.sellerId() == buyerId) {
                throw new BusinessError("PRODUCT_NOT_AVAILABLE", 409, "商品当前不可交易");
            }
        }

        @Override
        public void requireNoOccupancy(TradePorts.ProductState state, long tradeId) {
            var holder = state.occupancyTradeId();
            if (holder != null && holder != tradeId) {
                throw new BusinessError("OCCUPANCY_CONFLICT", 409, "商品已被其他交易占用");
            }
        }

        @Override
        public void acquire(WriteTransaction transaction, TradePorts.ProductState state, long tradeId) {
            writeProduct(transaction, "fixture.product.acquire", state.productId(), tradeId);
        }

        @Override
        public void release(WriteTransaction transaction, TradePorts.ProductState state, long tradeId,
                            String reason) {
            if (state.occupancyTradeId() == null || state.occupancyTradeId() != tradeId) {
                throw new BusinessError("OCCUPANCY_NOT_HELD", 409, "交易未持有商品占用");
            }
            writeProduct(transaction, "fixture.product.release", state.productId(), tradeId);
        }

        private void writeProduct(WriteTransaction transaction, String action, long productId, long tradeId) {
            transaction.audit(action, new ResourceRef("trade", tradeId), null,
                    json.createObjectNode().put("product_id", productId));
        }

        @Override
        public void requireCurrentSession(ExecutionContext context) {
            if (!SESSION.equals(context.sessionId())) {
                throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "fixture");
            }
        }

        @Override
        public TradePorts.AccountQualification qualification(long accountId) {
            return new TradePorts.AccountQualification(accountId, true, restricted.getOrDefault(accountId, false));
        }

        @Override
        public Map<Long, TradePorts.AccountProfile> profiles(Set<Long> accountIds) {
            var result = new ConcurrentHashMap<Long, TradePorts.AccountProfile>();
            accountIds.forEach(id -> result.put(id, new TradePorts.AccountProfile(id, "account-" + id, null)));
            return result;
        }

        @Override
        public long ensure(WriteTransaction transaction, long tradeId, long productId, long buyerId, long sellerId) {
            return tradeConversations.computeIfAbsent(tradeId, id -> {
                long conversation = conversationIds.incrementAndGet();
                conversationTrades.put(conversation, id);
                return conversation;
            });
        }

        @Override
        public OptionalLong find(long tradeId) {
            Long conversation = tradeConversations.get(tradeId);
            return conversation == null ? OptionalLong.empty() : OptionalLong.of(conversation);
        }

        @Override
        public void lockConversation(WriteTransaction transaction, long conversationId) {
            transaction.lock(new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(conversationId)),
                    () -> db.sql("SELECT true FROM pg_advisory_xact_lock(?)")
                            .param(0x5000_0000_0000_0000L + conversationId).query(Boolean.class).single());
        }

        @Override
        public void lockConversationRow(WriteTransaction transaction, long conversationId) {
            db.sql("SELECT true FROM pg_advisory_xact_lock(?)")
                    .param(0x5000_0000_0000_0000L + conversationId).query(Boolean.class).single();
        }

        long messageCount(long tradeId, String type) {
            long conversationId = find(tradeId).orElseThrow();
            return messages.stream().filter(message ->
                    message.conversationId() == conversationId && type.equals(message.type())).count();
        }

        @Override
        public void append(WriteTransaction transaction, long conversationId, UUID businessEventId,
                           String eventType, String body, ResourceRef sourceRef) {
            transaction.audit("fixture.conversation.append",
                    new ResourceRef("trade", conversationTrades.get(conversationId)), null,
                    json.createObjectNode().put("event_id", businessEventId.toString()));
            if (failAppend) {
                throw new BusinessError("TEST_CONVERSATION_FAILURE", 500, "fixture");
            }
            messages.add(new Message(conversationId, businessEventId, eventType, body,
                    sourceRef == null ? null : sourceRef.type()));
        }

        @Override
        public void archive(WriteTransaction transaction, long conversationId, long tradeId, String reason) {
            archived.add(conversationId);
        }

        @Override
        public void lockAndValidate(WriteTransaction transaction, long caseId, long managerId,
                                    long tradeId, String basisRef) {
            db.sql("SELECT true FROM pg_advisory_xact_lock(?)").param(0x6000_0000_0000_0000L + caseId)
                    .query(Boolean.class).single();
            if (basisRef == null || basisRef.isBlank()) {
                throw new BusinessError("BASIS_REQUIRED", 422, "缺少处置依据");
            }
        }

        @Override
        public long openTimeoutCase(WriteTransaction transaction, ExecutionContext context, long tradeId,
                                   String reason) {
            return timeoutCases.incrementAndGet() + tradeId;
        }

        @Override
        public long openDisputeCase(WriteTransaction transaction, ExecutionContext context, long tradeId,
                                    long disputeId, Instant at) {
            long caseId = caseStore.openDispute(tradeId, disputeId, at);
            disputeCases.put(disputeId, caseId);
            return caseId;
        }

        @Override
        public void register(WriteTransaction transaction, UUID businessEventId, String eventType,
                             long tradeId, Set<Long> recipients) {
            if (notifications != null) {
                notifications.register(transaction, businessEventId, eventType, tradeId, recipients);
                return;
            }
            transaction.addEventIntent(recipients, eventType.replace('.', '_'), 1,
                    new ResourceRef("trade", tradeId), eventType + ":" + businessEventId, null, null);
        }

        record Message(long conversationId, UUID businessEventId, String type, String body, String sourceType) {
        }
    }

    @TestConfiguration(proxyBeanMethods = false)
    public static class Fixtures {
        @Bean
        @Primary
        public MutableClock mutableClock() {
            return new MutableClock();
        }

        @Bean
        @Primary
        public FixturePorts fixturePorts(TradeTimeoutCases caseStore) {
            return new FixturePorts(caseStore);
        }

        @Bean
        @Primary
        public TradeActorResolver fixtureTradeActorResolver() {
            return request -> {
                var cookies = request.getCookies();
                if (cookies != null) {
                    for (Cookie cookie : cookies) {
                        if ("it_account".equals(cookie.getName())) {
                            return new TradeActorResolver.Actor(Long.parseLong(cookie.getValue()), SESSION, 1L);
                        }
                    }
                }
                throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "fixture");
            };
        }

        @Bean
        @Primary
        public CsrfGuard.Verifier csrfVerifier() {
            return (request, token) -> "it-csrf".equals(token);
        }
    }
}
