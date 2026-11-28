package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.product.application.ProductService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Real PostgreSQL check for administrator category correction (API-PRD-032).
 *
 * <p>Runs against the configured integration database with the shipped Flyway scripts applied and
 * Redis namespace isolated per run; every test cleans its own fixtures first, so shared integration
 * data is safe.
 */
class CategoryCorrectionIT {
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final String EMAIL_DOMAIN = "category-correction-it.example";
    private static final String EMAIL_LIKE = "%-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String SELLER_EMAIL = "seller-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String MANAGER_EMAIL = "manager-" + RUN_ID + "@" + EMAIL_DOMAIN;
    private static final String OTHER_MANAGER_EMAIL = "other-manager-" + RUN_ID + "@" + EMAIL_DOMAIN;

    private static final String MY_ACCOUNTS = "select account_id from account where email like ?";
    private static final String MY_PRODUCTS =
            "select product_id from product where seller_account_id in (" + MY_ACCOUNTS + ")";

    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static ProductService products;

    private static long seller;
    private static long manager;
    private static long otherManager;
    private static long productId;
    private static long oldCategory;
    private static long newCategory;
    private static long caseId;

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
        properties.setProperty("REDIS_NAMESPACE", namespace + ":category-correction:" + RUN_ID);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("CONFIG_VERSION", "category-correction-it");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        properties.setProperty("ACCOUNT_ENTRY_SIGNING_KEY", "category-correction-it-signing-key-0123456789");

        var application = new SpringApplication(BackendAppApplication.class,
                InfrastructureIT.Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("category-correction-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        products = app.getBean(ProductService.class);
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
        manager = account(MANAGER_EMAIL, "Manager", "manager");
        otherManager = account(OTHER_MANAGER_EMAIL, "Other manager", "manager");
        oldCategory = category("旧分类-" + RUN_ID);
        newCategory = category("新分类-" + RUN_ID);
        productId = db.sql("""
                        insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                        values (?, '旧书', 'description', 1000, 'public')
                        returning product_id
                        """)
                .param(seller).query(Long.class).single();
        db.sql("""
                        insert into product_category (product_id, category_id, source, created_by_kind, created_by_id)
                        values (?, ?, 'seller', 'seller', ?)
                        """)
                .param(productId).param(oldCategory).param(seller).update();
        caseId = reviewCase(productId, manager);
    }

    @Test
    void claimedManagerReplacesCategoriesRecordsHistoryAndNotifiesTheSeller() {
        var result = products.correctCategory(manager, productId,
                new ProductService.CorrectionCommand(List.of(Long.toString(newCategory)), "分类放错了", "case", caseId),
                accountContext(manager));

        assertThat(result.previousCategories()).extracting(entry -> entry.id())
                .containsExactly(Long.toString(oldCategory));
        assertThat(result.currentCategories()).extracting(entry -> entry.id())
                .containsExactly(Long.toString(newCategory));

        assertThat(db.sql("select content_version from product where product_id = ?")
                .param(productId).query(Integer.class).single()).isEqualTo(2);

        assertThat(db.sql("""
                        select removed_at is not null from product_category
                         where product_id = ? and category_id = ?
                        """).param(productId).param(oldCategory).query(Boolean.class).single()).isTrue();
        var added = db.sql("""
                        select source, created_by_kind, created_by_id, change_basis_type, change_basis_id
                          from product_category where product_id = ? and category_id = ?
                        """).param(productId).param(newCategory)
                .query((row, index) -> Map.of(
                        "source", row.getString("source"),
                        "kind", row.getString("created_by_kind"),
                        "by", row.getLong("created_by_id"),
                        "basis_type", row.getString("change_basis_type"),
                        "basis_id", row.getLong("change_basis_id")))
                .single();
        assertThat(added).containsEntry("source", "admin_correction")
                .containsEntry("kind", "admin")
                .containsEntry("by", manager)
                .containsEntry("basis_type", "case")
                .containsEntry("basis_id", caseId);

        var history = db.sql("""
                        select operator_kind, operator_account_id, edit_kind, reason, basis_type, basis_id,
                               before_content, after_content
                          from product_edit_history where product_id = ?
                        """).param(productId)
                .query((row, index) -> Map.of(
                        "operator_kind", row.getString("operator_kind"),
                        "operator", row.getLong("operator_account_id"),
                        "edit_kind", row.getString("edit_kind"),
                        "reason", row.getString("reason"),
                        "basis_type", row.getString("basis_type"),
                        "basis_id", row.getLong("basis_id"),
                        "before", row.getString("before_content"),
                        "after", row.getString("after_content")))
                .single();
        assertThat(history).containsEntry("operator_kind", "admin")
                .containsEntry("operator", manager)
                .containsEntry("edit_kind", "category_correction")
                .containsEntry("reason", "分类放错了")
                .containsEntry("basis_type", "case")
                .containsEntry("basis_id", caseId);
        assertThat(String.valueOf(history.get("before"))).contains(Long.toString(oldCategory));
        assertThat(String.valueOf(history.get("after"))).contains(Long.toString(newCategory));

        assertThat(db.sql("""
                        select count(*) from notification
                         where recipient_account_id = ? and event_type = 'product.category_corrected'
                           and source_type = 'product_category_correction'
                        """).param(seller).query(Long.class).single()).isEqualTo(1);
    }

    @Test
    void aManagerWhoDoesNotClaimTheCaseIsRejected() {
        assertFailure(() -> products.correctCategory(otherManager, productId,
                new ProductService.CorrectionCommand(List.of(Long.toString(newCategory)), "分类放错了", "case", caseId),
                accountContext(otherManager)), "ACTION_NOT_ALLOWED");

        assertThat(db.sql("select count(*) from product_edit_history where product_id = ?")
                .param(productId).query(Long.class).single()).isZero();
        assertThat(db.sql("select content_version from product where product_id = ?")
                .param(productId).query(Integer.class).single()).isEqualTo(1);
    }

    @Test
    void aNonManagerAccountIsRejectedByTheClaimCheck() {
        assertFailure(() -> products.correctCategory(seller, productId,
                new ProductService.CorrectionCommand(List.of(Long.toString(newCategory)), "分类放错了", "case", caseId),
                accountContext(seller)), "ACTION_NOT_ALLOWED");
    }

    private static ExecutionContext accountContext(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), UUID.randomUUID(), null, 1L, "category-correction-it");
    }

    private static long account(String email, String displayName, String role) {
        return db.sql("""
                        insert into account (email, display_name, password_hash, credential_version, role, created_at)
                        values (?, ?, '{$2a}$it', 1, ?, now())
                        returning account_id
                        """)
                .param(email).param(displayName).param(role).query(Long.class).single();
    }

    private static long category(String name) {
        long id = db.sql("insert into category (created_by_admin_id) values (?) returning category_id")
                .param(seller).query(Long.class).single();
        db.sql("""
                        insert into category_name (category_id, name, name_kind)
                        values (?, ?, 'main')
                        """).param(id).param(name).update();
        return id;
    }

    private static long reviewCase(long productId, long claimedManager) {
        long id = db.sql("""
                        insert into moderation_case (case_type, created_at, claimed_manager_id, claimed_at)
                        values ('product_review', now(), ?, now())
                        returning id
                        """)
                .param(claimedManager).query(Long.class).single();
        db.sql("""
                        insert into product_audit (product_id, sequence_no, case_id, status, submitted_at)
                        values (?, 1, ?, 'pending', now())
                        """)
                .param(productId).param(id).update();
        return id;
    }

    /** Removes only rows created by this test domain, so a shared integration database is safe. */
    private static void cleanupFixtures() {
        for (String table : List.of("notification", "user_event", "account_event_head")) {
            String column = "account_event_head".equals(table) ? "account_id" : "recipient_account_id";
            db.sql("delete from " + table + " where " + column + " in (" + MY_ACCOUNTS + ")")
                    .param(EMAIL_LIKE).update();
        }
        db.sql("delete from product_edit_history where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from product_category where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from product_audit where product_id in (" + MY_PRODUCTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from moderation_case where claimed_manager_id in (" + MY_ACCOUNTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from product where seller_account_id in (" + MY_ACCOUNTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from category_name where category_id in (select category_id from category"
                + " where created_by_admin_id in (" + MY_ACCOUNTS + "))").param(EMAIL_LIKE).update();
        db.sql("delete from category where created_by_admin_id in (" + MY_ACCOUNTS + ")")
                .param(EMAIL_LIKE).update();
        db.sql("delete from account where email like ?").param(EMAIL_LIKE).update();
    }

    private static void assertFailure(Runnable action, String code) {
        assertThatThrownBy(action::run)
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo(code));
    }
}
