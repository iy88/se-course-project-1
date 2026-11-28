package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.EmailDeliveryService;
import io.github.iy88.project1.account.application.EmailVerificationService;
import io.github.iy88.project1.account.application.EntryTokenService;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.category.application.CategoryService;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.product.application.ProductService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Properties;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;

class S2CoreIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static StringRedisTemplate redis;
    private static String namespace;

    @BeforeAll
    static void startApplication() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        namespace = properties.getProperty("REDIS_NAMESPACE") + ":s2core:" + RUN_ID;
        properties.setProperty("REDIS_NAMESPACE", namespace);
        properties.setProperty("ALLOWED_ORIGINS", "http://127.0.0.1:3000");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        var application = new SpringApplication(BackendAppApplication.class,
                InfrastructureIT.Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("integration", properties)));
        app = application.run("--spring.profiles.active=infrastructure",
                "--server.port=0", "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        redis = app.getBean(StringRedisTemplate.class);
    }

    @AfterAll
    static void stopApplication() {
        if (app == null) return;
        var context = app;
        try (context) {
            var keys = redis.keys(namespace + ":session:*");
            if (keys != null) {
                keys.forEach(redis::delete);
            }
        }
    }

    @Test
    void accountProductAndVerificationDeliveryWorkTogether() {
        var suffix = RUN_ID.toString().substring(0, 8);
        var email = "s2core-" + suffix + "@example.com";
        var password = "S2CorePassword2026";
        var accounts = app.getBean(AccountRepository.class);
        var hasher = app.getBean(PasswordHasher.class);
        var account = accounts.save(new Account(email, "S2 Core " + suffix, hasher.hash(password), Instant.now()));

        var sessions = app.getBean(SessionService.class);
        var issued = app.getBean(AccountService.class).login(email, password);
        var identity = sessions.authenticate(issued.token());
        assertThat(identity.account().id()).isEqualTo(account.id());
        sessions.revoke(identity);

        try {
            var auditContext = new AuditContext(new ExecutionContext(UUID.randomUUID(),
                    ExecutionContext.ActorKind.ACCOUNT, Long.toString(account.id()), UUID.randomUUID(), null, 1L,
                    "s2-core-it"), UUID.randomUUID());
            var category = app.getBean(CategoryService.class).create(account.id(), "Core " + suffix, auditContext);
            long categoryId = Long.parseLong(category.id());
            var products = app.getBean(ProductService.class);
            var proposedCategoryName = "Applied core " + suffix;
            var created = products.create(account.id(), new ProductService.CreateCommand(
                    "Core product " + suffix, "Integration product", List.of(), 1_200L,
                    List.of(category.id()), proposedCategoryName), auditContext);
            long productId = Long.parseLong(created.id());
            assertThat(created.lifecycleState()).isEqualTo("pending_review");
            assertThat(created.categoryApplication()).isNotNull();
            assertThat(created.categoryApplication().proposedName()).isEqualTo(proposedCategoryName);
            assertThat(created.categoryApplication().status()).isEqualTo("pending");

            db.sql("UPDATE product SET lifecycle_state = 'public' WHERE product_id = ?").param(productId).update();
            db.sql("""
                            UPDATE product_audit SET status = 'passed', decided_by_admin_id = ?, decided_at = now()
                            WHERE product_id = ?
                            """)
                    .param(account.id()).param(productId).update();

            var search = products.search(account.id(), "Core product " + suffix, null, null, null, 1, 10);
            assertThat(search.total()).isEqualTo(1);
            var detail = products.detail(account.id(), productId);
            assertThat(detail.lifecycleState()).isEqualTo("public");
            var mine = products.myResources(account.id(), null, 1, 10);
            assertThat(mine.items()).extracting(element -> element.productId())
                    .contains(Long.toString(productId));

            var entry = app.getBean(EntryTokenService.class).issue();
            var request = app.getBean(EmailVerificationService.class)
                    .request("registration", "mail-" + suffix + "@example.com",
                            app.getBean(EntryTokenService.class).parse(entry.cookie()), null);
            long verificationId = request.requests().getFirst().verificationId();
            var pending = app.getBean(EmailDeliveryService.class).claim(200, 3, 60).stream()
                    .filter(item -> item.id() == verificationId)
                    .findFirst()
                    .orElseThrow();
            assertThat(pending.purpose()).isEqualTo("registration");
            app.getBean(EmailDeliveryService.class).markSent(pending.id(), pending.leaseToken(), Instant.now());
            var sentAt = db.sql("SELECT sent_at FROM email_verification WHERE id = ?")
                    .param(verificationId).query(java.sql.Timestamp.class).single();
            assertThat(sentAt).isNotNull();

            db.sql("DELETE FROM email_verification WHERE id = ?").param(verificationId).update();
            db.sql("DELETE FROM product_edit_history WHERE product_id = ?").param(productId).update();
            db.sql("DELETE FROM category_application WHERE product_id = ?").param(productId).update();
            db.sql("DELETE FROM product_audit WHERE product_id = ?").param(productId).update();
            db.sql("DELETE FROM product_category WHERE product_id = ?").param(productId).update();
            db.sql("DELETE FROM product WHERE product_id = ?").param(productId).update();
            db.sql("DELETE FROM category_name WHERE category_id = ?").param(categoryId).update();
            db.sql("DELETE FROM category WHERE category_id = ?").param(categoryId).update();
        } finally {
            db.sql("DELETE FROM session_revocation WHERE session_id = ?").param(issued.sessionId()).update();
            db.sql("DELETE FROM session_guard WHERE session_id = ?").param(issued.sessionId()).update();
            db.sql("DELETE FROM account WHERE account_id = ?").param(account.id()).update();
        }
    }
}
