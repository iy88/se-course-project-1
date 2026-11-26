package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.trade.application.TradeOwnedReadModel;
import io.github.iy88.project1.trade.application.TradeReviewReadModel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Properties;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * Focused PostgreSQL verification of the S3 account read projections and the product edit notice
 * targets. It seeds only run-scoped rows and removes them afterwards.
 */
class S3OwnedReadModelIT {
    private static final UUID RUN = UUID.randomUUID();
    private static final Instant BASE = Instant.parse("2026-11-23T00:00:00Z");

    private static JdbcClient db;
    private static TradeOwnedReadModel trades;
    private static TradeReviewReadModel reviews;
    private static long seller;
    private static long buyerA;
    private static long buyerB;
    private static long productOne;
    private static long productTwo;
    private static long productThree;
    private static long productFour;
    private static long tradeOne;
    private static long tradeTwo;
    private static long tradeThree;
    private static long tradeFour;
    private static long tradeFive;

    @BeforeAll
    static void connectAndSeed() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        String database = System.getProperty("it.database", "").trim();
        String url = properties.getProperty("DATABASE_URL");
        String user = properties.getProperty("DATABASE_USERNAME");
        String password = properties.getProperty("DATABASE_PASSWORD");
        if (!database.isEmpty()) {
            url = url.replaceFirst("/[^/?]+(\\?|$)", "/" + database + "$1");
            user = properties.getProperty("DATABASE_OWNER_USERNAME");
            password = properties.getProperty("DATABASE_OWNER_PASSWORD");
        }
        db = JdbcClient.create(new DriverManagerDataSource(url, user, password));
        trades = new TradeOwnedReadModel(db);
        reviews = new TradeReviewReadModel(db);
        seed();
    }

    @AfterAll
    static void cleanup() {
        if (db == null) {
            return;
        }
        String email = "s3-read-%-" + RUN + "@example.com";
        boolean reviewTable = db.sql("""
                        select exists (select 1 from information_schema.tables
                                        where table_schema = 'public' and table_name = 'trade_review')
                        """).query(Boolean.class).single();
        if (reviewTable) {
            db.sql("""
                            delete from trade_review where trade_id in
                                (select id from trade where seller_id in
                                    (select account_id from account where email like ?))
                            """).param(email).update();
        }
        db.sql("""
                        update trade set active_agreement_id = null where seller_id in
                            (select account_id from account where email like ?)
                        """).param(email).update();
        db.sql("""
                        delete from trade_confirmation
                         where trade_id in (select id from trade where seller_id in
                             (select account_id from account where email like ?))
                        """).param(email).update();
        db.sql("""
                        delete from cancellation_proposal
                         where trade_id in (select id from trade where seller_id in
                             (select account_id from account where email like ?))
                        """).param(email).update();
        db.sql("""
                        delete from agreement_version
                         where trade_id in (select id from trade where seller_id in
                             (select account_id from account where email like ?))
                        """).param(email).update();
        db.sql("""
                        delete from trade_item_snapshot
                         where trade_id in (select id from trade where seller_id in
                             (select account_id from account where email like ?))
                        """).param(email).update();
        db.sql("""
                        delete from trade where seller_id in
                            (select account_id from account where email like ?)
                        """).param(email).update();
        db.sql("""
                        delete from product where seller_account_id in
                            (select account_id from account where email like ?)
                        """).param(email).update();
        db.sql("delete from account where email like ?").param(email).update();
    }

    @Test
    void totalsAndTradeResourcesUseTheBuyerOrSellerRole() {
        var totals = trades.totals(buyerA);
        assertThat(totals.total()).isEqualTo(4);
        assertThat(totals.buying()).isEqualTo(4);
        assertThat(totals.selling()).isZero();

        var page = trades.resources(buyerA, "buying", "in_progress", 10, 0);
        assertThat(page.total()).isEqualTo(3);
        assertThat(page.items()).allSatisfy(item -> {
            assertThat(item.role()).isEqualTo("buyer");
            assertThat(item.state()).isEqualTo("in_progress");
            assertThat(item.productTitle()).isNotNull();
        });
    }

    @Test
    void currentTodosFollowTheActionPredicatesAndCountsStayKindIndependent() {
        var all = trades.todos(seller, null, true, 20, 0);
        assertThat(all.total()).isEqualTo(2);
        assertThat(all.countsByKind()).containsEntry("request_response", 2L)
                .containsEntry("agreement_response", 0L);

        var buyer = trades.todos(buyerA, null, true, 20, 0);
        assertThat(buyer.total()).isEqualTo(3);
        assertThat(buyer.items()).extracting(TradeOwnedReadModel.TodoRow::kind)
                .containsExactly("cancellation_response", "completion_response", "agreement_response");
        assertThat(buyer.countsByKind()).containsEntry("agreement_response", 1L)
                .containsEntry("completion_response", 1L)
                .containsEntry("cancellation_response", 1L);

        var completion = trades.todos(buyerA, "completion_response", true, 20, 0);
        assertThat(completion.total()).isEqualTo(1);
        assertThat(completion.items().getFirst().tradeId()).isEqualTo(tradeFour);
    }

    @Test
    void endedTradesAndFrozenTradesDoNotProduceTodosOrNoticeTargets() {
        db.sql("update trade set status = 'completed', terminal_reason = 'completed', ended_at = ? where id = ?")
                .param(at(BASE.plusSeconds(90))).param(tradeTwo).update();
        try {
            assertThat(trades.productNoticeTargets(productOne)).extracting(TradeOwnedReadModel.ProductNoticeTarget::tradeId)
                    .containsExactly(tradeOne);
            assertThat(trades.totals(seller).total()).isEqualTo(5);
        } finally {
            db.sql("update trade set status = 'pending_acceptance', terminal_reason = null, ended_at = null where id = ?")
                    .param(tradeTwo).update();
        }
    }

    @Test
    void buyerHistoryScopeUsesTheExactTradeOrTheEarliestMatchingRequest() {
        assertThat(trades.buyerHistoryStart(productOne, buyerA, null)).contains(BASE.plusSeconds(10));
        assertThat(trades.buyerHistoryStart(productOne, buyerA, tradeOne)).contains(BASE.plusSeconds(10));
        assertThat(trades.buyerHistoryStart(productOne, buyerA, tradeTwo)).isEmpty();
        assertThat(trades.buyerHistoryStart(productTwo, buyerB, null)).isEmpty();
    }

    @Test
    void reviewProjectionIsUnavailableWithoutTheAgreedTableOrReadsVisibleFactsWithIt() {
        boolean present = db.sql("""
                        select exists (select 1 from information_schema.tables
                                        where table_schema = 'public' and table_name = 'trade_review')
                        """).query(Boolean.class).single();
        if (!present) {
            try {
                reviews.counts(buyerA);
                org.assertj.core.api.Assertions.fail("Expected DEPENDENCY_UNAVAILABLE");
            } catch (BusinessError error) {
                assertThat(error.code()).isEqualTo("DEPENDENCY_UNAVAILABLE");
            }
            return;
        }
        db.sql("""
                        insert into trade_review (trade_id, reviewer_id, reviewee_id, rating, content, visible, created_at)
                        values (?, ?, ?, 5, 'ok', true, ?)
                        """).param(tradeThree).param(buyerA).param(seller).param(at(BASE.plusSeconds(100))).update();
        try {
            assertThat(reviews.counts(buyerA)).isEqualTo(new TradeReviewReadModel.EvaluationCounts(1, 0));
            assertThat(reviews.page(buyerA, "written", 20, 0).items()).singleElement()
                    .satisfies(row -> assertThat(row.content()).isEqualTo("ok"));
        } finally {
            db.sql("delete from trade_review where trade_id = ?").param(tradeThree).update();
        }
    }

    private static void seed() {
        seller = account("seller");
        buyerA = account("buyer-a");
        buyerB = account("buyer-b");
        productOne = product("待接受请求");
        productTwo = product("约定待回应");
        productThree = product("完成待确认");
        productFour = product("取消待回应");
        tradeOne = trade(productOne, buyerA, "pending_acceptance", BASE.plusSeconds(10));
        tradeTwo = trade(productOne, buyerB, "pending_acceptance", BASE.plusSeconds(20));
        tradeThree = trade(productTwo, buyerA, "in_progress", BASE.plusSeconds(30));
        tradeFour = trade(productThree, buyerA, "in_progress", BASE.plusSeconds(40));
        tradeFive = trade(productFour, buyerA, "in_progress", BASE.plusSeconds(50));

        long agreementThree = agreement(tradeThree, null, "proposed", seller, BASE.plusSeconds(60));
        long agreementFour = agreement(tradeFour, null, "effective", seller, BASE.plusSeconds(70));
        long agreementFive = agreement(tradeFive, null, "effective", seller, BASE.plusSeconds(80));
        db.sql("update trade set active_agreement_id = ? where id = ?").param(agreementFour).param(tradeFour).update();
        db.sql("update trade set active_agreement_id = ? where id = ?").param(agreementFive).param(tradeFive).update();
        db.sql("""
                        insert into trade_confirmation
                            (trade_id, agreement_id, confirmer_id, note, submitted_at, business_event_id)
                        values (?, ?, ?, 'done', ?, ?)
                        """).param(tradeFour).param(agreementFour).param(seller).param(at(BASE.plusSeconds(90)))
                .param(UUID.randomUUID()).update();
        db.sql("""
                        insert into cancellation_proposal
                            (trade_id, proposed_by, mode, reason, status, proposed_at, business_event_id)
                        values (?, ?, 'approval', 'cancel', 'pending', ?, ?)
                        """).param(tradeFive).param(seller).param(at(BASE.plusSeconds(95)))
                .param(UUID.randomUUID()).update();
    }

    private static long account(String role) {
        return db.sql("""
                        insert into account (email, display_name, password_hash)
                        values (?, ?, 'hash') returning account_id
                        """).param("s3-read-" + role + "-" + RUN + "@example.com").param("S3 " + role)
                .query(Long.class).single();
    }

    private static long product(String title) {
        return db.sql("""
                        insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                        values (?, ?, '测试商品', 1200, 'public') returning product_id
                        """).param(seller).param(title + "-" + RUN).query(Long.class).single();
    }

    private static long trade(long product, long buyer, String status, Instant requestedAt) {
        return db.sql("""
                        insert into trade (product_id, buyer_id, seller_id, status, requested_at, created_at, updated_at)
                        values (?, ?, ?, ?, ?, ?, ?) returning id
                        """).param(product).param(buyer).param(seller).param(status).param(at(requestedAt))
                .param(at(requestedAt)).param(at(requestedAt)).query(Long.class).single();
    }

    private static long agreement(long trade, Long base, String status, long proposedBy, Instant proposedAt) {
        return db.sql("""
                        insert into agreement_version
                            (trade_id, base_agreement_id, version_no, status, proposed_by, delivery_at,
                             delivery_place_text, delivery_method, amount_cents, payment_method, payment_timing,
                             proposed_at, business_event_id)
                        values (?, ?, 1, ?, ?, ?, '图书馆', '自提', 1200, '现金', '交付时', ?, ?)
                        returning id
                        """).param(trade).param(base).param(status).param(proposedBy).param(at(proposedAt))
                .param(at(proposedAt)).param(UUID.randomUUID()).query(Long.class).single();
    }

    private static OffsetDateTime at(Instant instant) {
        return OffsetDateTime.ofInstant(instant, ZoneOffset.UTC);
    }
}
