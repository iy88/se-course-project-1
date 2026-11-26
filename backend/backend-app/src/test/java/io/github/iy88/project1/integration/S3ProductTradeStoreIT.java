package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.persistence.JdbcProductTradeStore;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Focused PostgreSQL verification of concurrent occupancy using separate database connections.
 */
class S3ProductTradeStoreIT {
    private static final UUID RUN = UUID.randomUUID();

    private static JdbcClient db;
    private static TransactionTemplate transaction;
    private static JdbcProductTradeStore store;

    @BeforeAll
    static void connect() throws Exception {
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
        var dataSource = new DriverManagerDataSource(url, user, password);
        db = JdbcClient.create(dataSource);
        transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        store = new JdbcProductTradeStore(db);
    }

    @AfterAll
    static void cleanup() {
        if (db == null) {
            return;
        }
        deleteRunData();
    }

    @Test
    void occupancyIsAcquiredByOneConcurrentTradeAndReleasedOffShelf() throws Exception {
        long seller = account("seller");
        long buyerOne = account("buyer-one");
        long buyerTwo = account("buyer-two");
        long category = category(seller);
        long product = product(seller, category);

        var read = store.read(product).orElseThrow();
        assertThat(read.lifecycleState()).isEqualTo("public");
        assertThat(read.categoryNames()).containsExactly("旧书-" + RUN);
        assertThat(read.occupiedByTradeId()).isNull();

        long tradeOne = 9_000_001;
        long tradeTwo = 9_000_002;
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch go = new CountDownLatch(1);
        ExecutorService threads = Executors.newFixedThreadPool(2);
        try {
            Future<Object> first = threads.submit(() -> acquire(product, tradeOne, ready, go));
            Future<Object> second = threads.submit(() -> acquire(product, tradeTwo, ready, go));
            assertThat(ready.await(10, TimeUnit.SECONDS)).isTrue();
            go.countDown();
            List<Object> outcomes = List.of(first.get(20, TimeUnit.SECONDS), second.get(20, TimeUnit.SECONDS));

            List<Long> winners = outcomes.stream().filter(Long.class::isInstance).map(Long.class::cast).toList();
            assertThat(winners).hasSize(1);
            assertThat(outcomes).filteredOn(BusinessError.class::isInstance)
                    .singleElement()
                    .isInstanceOfSatisfying(BusinessError.class,
                            error -> assertThat(error.code()).isEqualTo("PRODUCT_NOT_AVAILABLE"));
            long winner = winners.getFirst();
            long loser = winner == tradeOne ? tradeTwo : tradeOne;

            var occupied = store.read(product).orElseThrow();
            assertThat(occupied.lifecycleState()).isEqualTo("in_trade");
            assertThat(occupied.occupiedByTradeId()).isEqualTo(winner);
            assertThat(occupied.title()).isEqualTo("旧书交易");

            assertThat(assertThatThrownByRelease(product, loser).code()).isEqualTo("OCCUPANCY_NOT_HELD");

            transaction.executeWithoutResult(status -> store.release(product, winner, Instant.now()));
            var released = store.read(product).orElseThrow();
            assertThat(released.lifecycleState()).isEqualTo("off_shelf");
            assertThat(released.occupiedByTradeId()).isNull();
        } finally {
            threads.shutdownNow();
        }
    }

    private static Object acquire(long product, long tradeId, CountDownLatch ready, CountDownLatch go) {
        ready.countDown();
        try {
            if (!go.await(10, TimeUnit.SECONDS)) {
                throw new IllegalStateException("concurrent acquire did not start");
            }
            transaction.executeWithoutResult(status -> {
                store.lock(product).orElseThrow();
                store.acquire(product, tradeId, Instant.now());
            });
            return tradeId;
        } catch (BusinessError rejected) {
            return rejected;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(interrupted);
        }
    }

    private static BusinessError assertThatThrownByRelease(long product, long tradeId) {
        try {
            transaction.executeWithoutResult(status -> store.release(product, tradeId, Instant.now()));
        } catch (BusinessError rejected) {
            return rejected;
        }
        throw new AssertionError("Expected OCCUPANCY_NOT_HELD");
    }

    private static long account(String role) {
        return db.sql("""
                        insert into account (email, display_name, password_hash)
                        values (?, ?, ?) returning account_id
                        """)
                .param("s3-" + role + "-" + RUN + "@example.com").param("S3 " + role).param("hash")
                .query(Long.class).single();
    }

    private static long category(long manager) {
        long id = db.sql("insert into category (created_by_admin_id) values (?) returning category_id")
                .param(manager).query(Long.class).single();
        db.sql("insert into category_name (category_id, name, name_kind) values (?, ?, 'main')")
                .param(id).param("旧书-" + RUN).update();
        return id;
    }

    private static long product(long seller, long category) {
        long id = db.sql("""
                        insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                        values (?, '旧书交易', '测试商品', 1200, 'public') returning product_id
                        """)
                .param(seller).query(Long.class).single();
        db.sql("""
                        insert into product_category (product_id, category_id, source, created_by_kind, created_by_id)
                        values (?, ?, 'seller', 'seller', ?)
                        """)
                .param(id).param(category).param(seller).update();
        return id;
    }

    private static void deleteRunData() {
        db.sql("""
                        delete from product_category
                         where product_id in (select product_id from product
                                               where seller_account_id in (select account_id from account
                                                                            where email like ?))
                        """).param("s3-%-" + RUN + "@example.com").update();
        db.sql("delete from product where seller_account_id in (select account_id from account where email like ?)")
                .param("s3-%-" + RUN + "@example.com").update();
        db.sql("delete from category_name where category_id in (select category_id from category where created_by_admin_id in (select account_id from account where email like ?))")
                .param("s3-%-" + RUN + "@example.com").update();
        db.sql("delete from category where created_by_admin_id in (select account_id from account where email like ?)")
                .param("s3-%-" + RUN + "@example.com").update();
        db.sql("delete from account where email like ?").param("s3-%-" + RUN + "@example.com").update();
    }
}
