package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductInteractions;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Real PostgreSQL and Redis check for product interaction (S2-04). The database is the isolated
 * {@code project1_s2_04_it} database with the shipped Flyway scripts already applied; every test
 * cleans its own fixtures first, so no developer data is touched.
 */
class ProductInteractionIT {
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final String EMAIL_DOMAIN = "interaction-it.example";
    private static final String EMAIL_LIKE = "%-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String SELLER_EMAIL = "seller-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String BUYER_EMAIL = "buyer-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String OTHER_EMAIL = "other-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String MANAGER_EMAIL = "manager-" + RUN_ID + "@" + EMAIL_DOMAIN;

    private static final String MY_ACCOUNTS = "select account_id from account where email like ?";
    private static final String MY_PRODUCTS =
            "select product_id from product where seller_account_id in (" + MY_ACCOUNTS + ")";

    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static ProductInteractions interactions;

    private static long seller;
    private static long buyer;
    private static long other;
    private static long manager;
    private static long publicProduct;
    private static long hiddenProduct;

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
        properties.setProperty("REDIS_NAMESPACE", namespace + ":interaction:" + RUN_ID);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("CONFIG_VERSION", "interaction-it");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        properties.setProperty("ACCOUNT_ENTRY_SIGNING_KEY", "product-interaction-it-signing-key-0123456789");

        var application = new SpringApplication(BackendAppApplication.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("product-interaction-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        interactions = app.getBean(ProductInteractions.class);
    }

    @AfterAll
    static void stopApplication() {
        try {
            if (db != null) {
                cleanupFixtures();
            }
        } finally {
            if (app != null) {
                app.close();
            }
        }
    }

    @BeforeEach
    void resetFixtures() {
        cleanupFixtures();
        seller = account(SELLER_EMAIL, "Seller", "user");
        buyer = account(BUYER_EMAIL, "Buyer", "user");
        other = account(OTHER_EMAIL, "Other", "user");
        manager = account(MANAGER_EMAIL, "Manager", "manager");
        publicProduct = product(seller, "Public book", "public");
        hiddenProduct = product(seller, "Hidden book", "off_shelf");
    }

    /** Removes only rows created by this test domain, so a shared integration database is safe. */
    private static void cleanupFixtures() {
        db.sql("delete from product_favorite where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from product_comment where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from product_audit where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from moderation_case where claimed_manager_id in (" + MY_ACCOUNTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from product where seller_account_id in (" + MY_ACCOUNTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from account where email like ?").param(EMAIL_LIKE).update();
    }

    @Test
    void favouriteSurvivesHidingAndHidesInvalidContent() {
        var added = interactions.addFavorite(buyer, publicProduct);
        var repeated = interactions.addFavorite(buyer, publicProduct);

        assertThat(repeated.favoritedAt()).isEqualTo(added.favoritedAt());
        assertThat(count("product_favorite")).isEqualTo(1);

        db.sql("update product set lifecycle_state = 'off_shelf' where product_id = ?")
                .param(publicProduct).update();
        var status = interactions.favoriteStatus(buyer, publicProduct);
        assertThat(status.favorited()).isTrue();
        assertThat(status.valid()).isFalse();

        var page = interactions.listFavorites(buyer, 1, 20);
        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.status()).isEqualTo("invalid");
            assertThat(item.product()).isNull();
            assertThat(item.message()).isEqualTo("该商品已失效");
        });

        var invalid = interactions.listFavoriteResources(buyer, "invalid", 1, 1);
        assertThat(invalid.total()).isEqualTo(1);
        assertThat(invalid.items()).singleElement().satisfies(item -> {
            assertThat(item.favoriteId()).isNotBlank();
            assertThat(item.updatedAt()).isEqualTo(added.favoritedAt());
            assertThat(item.state()).isEqualTo("invalid");
            assertThat(item.productSummary()).isNull();
        });
        assertThat(interactions.listFavoriteResources(buyer, "valid", 1, 1).total()).isZero();
        assertFailure(() -> interactions.listFavoriteResources(buyer, "public", 1, 1), "INPUT_INVALID");

        interactions.removeFavorite(buyer, publicProduct);
        assertThat(count("product_favorite")).isZero();
        assertFailure(() -> interactions.favoriteStatus(buyer, publicProduct), "RESOURCE_NOT_VISIBLE");
    }

    @Test
    void hiddenProductOnlyAcceptsFavouritesWhilePublic() {
        assertFailure(() -> interactions.addFavorite(buyer, hiddenProduct), "RESOURCE_NOT_VISIBLE");
        assertThat(count("product_favorite")).isZero();
    }

    @Test
    void commentThreadSupportsSellerReplyAndAuthorDeletion() {
        var comment = interactions.createComment(buyer, publicProduct, "  Is it still available?  ");
        long commentId = Long.parseLong(comment.id());
        assertThat(comment.status()).isEqualTo("published");
        assertThat(comment.body()).isEqualTo("Is it still available?");

        var reply = interactions.replyToComment(seller, publicProduct, commentId, "Yes, come by tonight.");
        assertThat(reply.replyToCommentId()).isEqualTo(Long.toString(commentId));

        var page = interactions.listComments(other, publicProduct, 1, 20, null);
        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.replies()).singleElement().satisfies(sellerReply ->
                    assertThat(sellerReply.author().displayName()).isEqualTo("Seller"));
        });

        assertFailure(() -> interactions.replyToComment(buyer, publicProduct, commentId, "Mine"),
                "COMMENT_REPLY_NOT_ALLOWED");
        assertFailure(() -> interactions.replyToComment(seller, publicProduct,
                Long.parseLong(reply.id()), "Nested"), "STATE_CONFLICT");

        interactions.deleteComment(buyer, publicProduct, commentId);
        assertThat(db.sql("select deleted_at from product_comment where comment_id = ?")
                .param(commentId).query(java.time.OffsetDateTime.class).single()).isNotNull();
        assertThat(interactions.listComments(other, publicProduct, 1, 20, null).total()).isZero();

        interactions.deleteComment(buyer, publicProduct, commentId);
    }

    @Test
    void hiddenProductScopesReadersAndClaimedManagers() {
        var comment = interactions.createComment(buyer, publicProduct, "Please answer");
        long commentId = Long.parseLong(comment.id());
        db.sql("update product set lifecycle_state = 'off_shelf' where product_id = ?")
                .param(publicProduct).update();

        assertFailure(() -> interactions.listComments(other, publicProduct, 1, 20, null),
                "RESOURCE_NOT_VISIBLE");
        assertThat(interactions.listComments(buyer, publicProduct, 1, 20, null).items())
                .singleElement().satisfies(item -> assertThat(item.body()).isEqualTo("Please answer"));

        long caseId = reviewCase(publicProduct, manager);
        assertThat(interactions.listComments(manager, publicProduct, 1, 20, caseId).items()).hasSize(1);

        var removed = interactions.removeComment(manager, caseId, commentId, "E-1", "spam");
        assertThat(removed.authorAccountId()).isEqualTo(buyer);
        assertThat(removed.status()).isEqualTo("removed_by_admin");

        var managed = interactions.listComments(manager, publicProduct, 1, 20, caseId);
        assertThat(managed.items()).singleElement().satisfies(item -> {
            assertThat(item.status()).isEqualTo("removed_by_admin");
            assertThat(item.body()).isEqualTo("Please answer");
        });
        assertFailure(() -> interactions.deleteComment(buyer, publicProduct, commentId),
                "COMMENT_ALREADY_REMOVED");
        assertFailure(() -> interactions.listComments(other, publicProduct, 1, 20, caseId),
                "RESOURCE_NOT_VISIBLE");
        assertThat(db.sql("select basis_ref from product_comment where comment_id = ?")
                .param(commentId).query(String.class).single()).isEqualTo("case:" + caseId + ":enforcement:E-1");
    }

    @Test
    void commentFrequencyIsLimitedPerAccount() {
        for (int index = 0; index < 10; index++) {
            interactions.createComment(buyer, publicProduct, "message " + index);
        }

        assertFailure(() -> interactions.createComment(buyer, publicProduct, "one too many"), "RATE_LIMITED");
        assertThat(count("product_comment")).isEqualTo(10);
    }

    @Test
    void concurrentFavouritesResolveToOneRow() throws Exception {
        var barrier = new CyclicBarrier(2);
        Callable<Object> add = () -> {
            barrier.await(5, TimeUnit.SECONDS);
            return interactions.addFavorite(buyer, publicProduct);
        };
        try (var pool = Executors.newFixedThreadPool(2)) {
            var results = pool.invokeAll(List.of(add, add));
            var first = (ProductInteractions.FavoriteStatus) results.get(0).get();
            var second = (ProductInteractions.FavoriteStatus) results.get(1).get();
            assertThat(first.favoritedAt()).isEqualTo(second.favoritedAt());
        }
        assertThat(count("product_favorite")).isEqualTo(1);
    }

    private static long account(String email, String displayName, String role) {
        return db.sql("""
                        insert into account (email, display_name, password_hash, credential_version, role, created_at)
                        values (?, ?, '{$2a}$it', 1, ?, now())
                        returning account_id
                        """)
                .param(email).param(displayName).param(role).query(Long.class).single();
    }

    private static long product(long sellerId, String title, String state) {
        return db.sql("""
                        insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                        values (?, ?, 'description', 1000, ?)
                        returning product_id
                        """)
                .param(sellerId).param(title).param(state).query(Long.class).single();
    }

    private static long reviewCase(long productId, long claimedManager) {
        long caseId = db.sql("""
                        insert into moderation_case (case_type, created_at, claimed_manager_id, claimed_at)
                        values ('product_review', now(), ?, now())
                        returning id
                        """)
                .param(claimedManager).query(Long.class).single();
        db.sql("""
                        insert into product_audit (product_id, sequence_no, case_id, status, submitted_at)
                        values (?, 1, ?, 'pending', now())
                        """)
                .param(productId).param(caseId).update();
        return caseId;
    }

    private static long count(String table) {
        return db.sql("select count(*) from " + table + " where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).query(Long.class).single();
    }

    private static void assertFailure(Runnable action, String code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo(code));
    }
}
