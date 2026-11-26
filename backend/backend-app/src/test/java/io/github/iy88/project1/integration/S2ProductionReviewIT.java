package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.api.account.AccountCookies;
import io.github.iy88.project1.category.application.CategoryService;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.ExecutionContext;
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

class S2ProductionReviewIT {
    private static final String RUN = UUID.randomUUID().toString();
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String OSS_BUCKET = "project1-s2-tests";
    private static final String OSS_PREFIX = "s2-local";
    private static final String PASSWORD = "S2ProductionFixture920!";
    private static final List<SessionService.Issued> SESSIONS = new ArrayList<>();
    private static final List<Long> ACCOUNT_IDS = new ArrayList<>();
    private static final List<Long> CATEGORY_IDS = new ArrayList<>();
    private static final List<Long> FILE_IDS = new ArrayList<>();

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
        properties.setProperty("REDIS_NAMESPACE", properties.getProperty("REDIS_NAMESPACE") + ":s2-review:" + RUN);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        // URL signing is local. This test never reads or writes objects in an external bucket.
        properties.setProperty("OSS_ENDPOINT", "https://oss-s2-test.invalid");
        properties.setProperty("OSS_BUCKET", OSS_BUCKET);
        properties.setProperty("OSS_PREFIX", OSS_PREFIX);
        var application = new SpringApplication(BackendAppApplication.class,
                InfrastructureIT.Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("s2-production-review-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        var port = ((ServletWebServerApplicationContext) app).getWebServer().getPort();
        baseUrl = "http://127.0.0.1:" + port;
        db = app.getBean(JdbcClient.class);
        json = app.getBean(JsonMapper.class);
        http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }

    @AfterAll
    static void cleanup() {
        if (app == null) {
            return;
        }
        try (var context = app) {
            var sessions = app.getBean(SessionService.class);
            for (var issued : SESSIONS) {
                sessions.revoke(sessions.authenticate(issued.token()));
                db.sql("DELETE FROM session_revocation WHERE session_id = ?").param(issued.sessionId()).update();
                db.sql("DELETE FROM session_guard WHERE session_id = ?").param(issued.sessionId()).update();
            }
            for (long fileId : FILE_IDS) {
                db.sql("DELETE FROM file_reference WHERE file_id = ?").param(fileId).update();
                db.sql("DELETE FROM file_record WHERE file_id = ?").param(fileId).update();
            }
            for (var accountId : ACCOUNT_IDS) {
                deleteOwnedData(accountId);
            }
            for (var categoryId : CATEGORY_IDS) {
                db.sql("DELETE FROM category_name WHERE category_id = ?").param(categoryId).update();
                db.sql("DELETE FROM category WHERE category_id = ?").param(categoryId).update();
            }
            for (var accountId : ACCOUNT_IDS) {
                db.sql("DELETE FROM account WHERE account_id = ?").param(accountId).update();
            }
        } finally {
            if (http != null) {
                http.close();
            }
        }
    }

    @Test
    void realSessionsCanRejectResubmitApproveAndReadTheSellerNotifications() throws Exception {
        var seller = login("seller", false);
        var buyer = login("buyer", false);
        var manager = login("manager", true);
        var secondManager = login("other", true);
        String firstCategory = createCategory(manager, "Lit " + RUN);
        String secondCategory = createCategory(manager, "Course " + RUN);
        CATEGORY_IDS.addAll(List.of(Long.parseLong(firstCategory), Long.parseLong(secondCategory)));

        long image = uploadedImage(seller.account().id(), FilePurpose.PRODUCT_IMAGE, true);
        String createBody = """
                {"title":"Book %s", "description":"First edition", "price_cents":1500,
                 "category_ids":["%s","%s"], "image_file_ids":["%s"]}
                """.formatted(RUN, firstCategory, secondCategory, image);
        String createKey = key();
        var product = write(seller, "POST", "/products", createBody, createKey, 201);
        assertThat(write(seller, "POST", "/products", createBody, createKey, 201)).isEqualTo(product);
        String productId = text(product, "id");
        assertThat(db.sql("""
                        select count(*) from audit_record
                        where action = 'product.submitted' and target_type = 'product' and target_id = ?
                        """).param(Long.parseLong(productId)).query(Long.class).single()).isEqualTo(1);
        var pending = product.path("pending_review");
        String caseId = text(pending, "case_id");
        String auditId = text(pending, "audit_id");
        assertThat(text(product, "lifecycle_state")).isEqualTo("pending_review");
        get(buyer, "/products/" + productId, 404);
        get(buyer, "/management/todos", 403);
        var openItems = get(manager, "/management/todos?ownership=unclaimed", 200).path("items");
        assertThat(openItems).anySatisfy(item -> assertThat(text(item, "case_id")).isEqualTo(caseId));

        String claimPath = "/admin/cases/" + caseId + "/claim";
        write(buyer, "POST", claimPath, null, key(), 403);
        String claimKey = key();
        var claim = write(manager, "POST", claimPath, null, claimKey, 200);
        assertThat(write(manager, "POST", claimPath, null, claimKey, 200)).isEqualTo(claim);
        assertThat(db.sql("SELECT count(*) FROM operation_record WHERE idempotency_key = ?")
                .param(claimKey).query(Long.class).single()).isEqualTo(1);
        assertThat(text(write(secondManager, "POST", claimPath, null, key(), 409).path("error"), "code"))
                .isEqualTo("CASE_ALREADY_CLAIMED");
        String detailPath = "/admin/product-reviews/" + auditId;
        get(secondManager, detailPath, 404);
        var detail = get(manager, detailPath, 200);
        var content = detail.path("current_content");
        assertThat(content.path("categories").size()).isEqualTo(2);
        var reviewImage = content.path("images").get(0);
        assertThat(text(reviewImage, "file_id")).isEqualTo(Long.toString(image));
        assertThat(text(reviewImage, "url")).startsWith("https://");

        var blockedWithdrawal = write(seller, "POST", "/products/" + productId + "/withdrawal",
                version(product), key(), 409);
        assertThat(text(blockedWithdrawal.path("error"), "code")).isEqualTo("REVIEW_ALREADY_CLAIMED");
        String rejection = "{\"decision\":\"rejected\",\"reason\":\"Please update the description\"}";
        String decisionKey = key();
        var rejected = write(manager, "POST", detailPath + "/decision", rejection, decisionKey, 200);
        assertThat(text(rejected, "status")).isEqualTo("rejected");
        assertThat(write(manager, "POST", detailPath + "/decision", rejection, decisionKey, 200)).isEqualTo(rejected);
        assertThat(text(get(manager, detailPath, 200).path("review_result"), "reason"))
                .isEqualTo("Please update the description");
        var rejectedNotice = get(seller, "/account/notifications?event_type=product_audit.rejected", 200);
        assertThat(rejectedNotice.path("total").asLong()).isEqualTo(1);
        var notice = rejectedNotice.path("items").get(0);
        assertThat(text(notice, "summary")).isEqualTo("商品审核未通过");
        assertThat(text(notice, "subject")).isEqualTo(text(product, "title"));
        assertThat(notice.has("body")).isFalse();
        assertThat(text(notice.path("source"), "resource_id")).isEqualTo(productId);
        var noticeDetail = get(seller, "/account/notifications/" + text(notice, "notification_id"), 200);
        assertThat(text(noticeDetail, "body")).contains("Please update the description");
        assertThat(get(buyer, "/account/notifications", 200).path("total").asLong()).isZero();

        var edited = write(seller, "PATCH", "/products/" + productId,
                "{\"description\":\"Updated description\",\"expected_version\":"
                        + rejected.path("product").path("content_version").asInt() + "}", key(), 200);
        var resubmitted = write(seller, "POST", "/products/" + productId + "/review-submissions",
                version(edited), key(), 201);
        assertThat(text(resubmitted, "case_id")).isNotEqualTo(caseId);
        write(manager, "POST", "/admin/cases/" + text(resubmitted, "case_id") + "/claim", null, key(), 200);
        var approved = write(manager, "POST", "/admin/product-reviews/" + text(resubmitted, "audit_id") + "/decision",
                "{\"decision\":\"approved\"}", key(), 200);
        assertThat(text(approved, "status")).isEqualTo("passed");
        String completedReviews = "/management/todos?kind=product_review&keyword=Book%20" + RUN;
        var mine = get(manager, completedReviews + "&ownership=completed_mine", 200);
        assertThat(mine.path("total").asLong()).isEqualTo(2);
        assertThat(mine.path("items")).extracting(row -> row.path("decision_kind").asString())
                .containsExactly("approved", "rejected");
        var all = get(secondManager, completedReviews + "&ownership=completed_all", 200);
        assertThat(all.path("items")).isEqualTo(mine.path("items"));
        assertThat(get(secondManager, completedReviews + "&ownership=completed_mine", 200)
                .path("total").asLong()).isZero();
        get(secondManager, detailPath, 404);
        var publiclyVisible = get(buyer, "/products/" + productId, 200);
        assertThat(text(publiclyVisible, "description")).isEqualTo("Updated description");
        var page = get(buyer, "/products?category_ids=" + firstCategory + "," + secondCategory, 200);
        assertThat(page.path("items")).anySatisfy(item -> assertThat(text(item, "id")).isEqualTo(productId));
        assertThat(get(seller, "/account/notifications?event_type=product_audit.passed", 200)
                .path("total").asLong()).isEqualTo(1);
        String favoritePath = "/me/favorites/" + productId;
        write(buyer, "PUT", favoritePath, null, key(), 200);
        var favorites = get(buyer, "/account/resources?kind=favorite&state=valid", 200).path("items");
        assertThat(favorites).singleElement().satisfies(row -> {
            assertThat(text(row, "favorite_id")).isNotBlank();
            assertThat(text(row.path("product_summary"), "id")).isEqualTo(productId);
        });
        get(buyer, "/account/resources?kind=favorite&role=all", 422);
        write(seller, "POST", "/products/" + productId + "/off-shelf", version(publiclyVisible), key(), 200);
        var hiddenFavorite = get(buyer, "/account/resources?kind=favorite&state=invalid", 200).path("items").get(0);
        assertThat(text(hiddenFavorite, "state")).isEqualTo("invalid");
        assertThat(hiddenFavorite.path("product_summary").isNull()).isTrue();
    }

    @Test
    void profileReplacesAndReleasesOnlyOwnedVerifiedAvatarFiles() throws Exception {
        var owner = login("avatar", false);
        var other = login("avatar-other", false);
        long accountId = owner.account().id();
        String accountSession = "/account/session";
        String profile = "/account/profile";
        assertThat(get(owner, accountSession, 200).path("account").path("avatar_url").isNull()).isTrue();

        long initial = uploadedImage(accountId, FilePurpose.ACCOUNT_AVATAR, true);
        long replacement = uploadedImage(accountId, FilePurpose.ACCOUNT_AVATAR, true);
        long unverified = uploadedImage(accountId, FilePurpose.ACCOUNT_AVATAR, false);
        long wrongPurpose = uploadedImage(accountId, FilePurpose.PRODUCT_IMAGE, true);
        long foreign = uploadedImage(other.account().id(), FilePurpose.ACCOUNT_AVATAR, true);

        assertThat(text(write(owner, "PATCH", profile, avatar(initial), key(), 200), "avatar_url"))
                .startsWith("https://");
        assertThat(avatarReferences(accountId)).containsExactly(initial);
        write(owner, "PATCH", profile, avatar(foreign), key(), 404);
        write(owner, "PATCH", profile, avatar(unverified), key(), 409);
        write(owner, "PATCH", profile, avatar(wrongPurpose), key(), 422);
        assertThat(avatarReferences(accountId)).containsExactly(initial);

        write(owner, "PATCH", profile, avatar(replacement), key(), 200);
        assertThat(avatarReferences(accountId)).containsExactly(replacement);
        var removed = write(owner, "PATCH", profile, "{\"avatar_file_id\":null}", key(), 200);
        assertThat(removed.path("avatar_url").isNull()).isTrue();
        assertThat(avatarReferences(accountId)).isEmpty();
    }

    @Test
    void categoryCreateReplayWritesExactlyOneBusinessAudit() throws Exception {
        var manager = login("category-audit", true);
        String body = "{\"name\":\"Audit " + RUN + "\"}";
        String idempotencyKey = key();

        var created = write(manager, "POST", "/admin/categories", body, idempotencyKey, 201);
        assertThat(write(manager, "POST", "/admin/categories", body, idempotencyKey, 201)).isEqualTo(created);
        String categoryId = text(created, "id");
        CATEGORY_IDS.add(Long.parseLong(categoryId));
        assertThat(db.sql("""
                        select count(*) from audit_record
                        where action = 'category.created' and target_type = 'category' and target_id = ?
                        """).param(Long.parseLong(categoryId)).query(Long.class).single()).isEqualTo(1);
    }

    @Test
    void withdrawingAnUnclaimedReviewAllowsImageEditingAndResubmission() throws Exception {
        var seller = login("withdrawn-seller", false);
        var manager = login("withdrawn-manager", true);
        String category = createCategory(manager, "Draft " + RUN);
        CATEGORY_IDS.add(Long.parseLong(category));
        long firstImage = uploadedImage(seller.account().id(), FilePurpose.PRODUCT_IMAGE, true);
        long nextImage = uploadedImage(seller.account().id(), FilePurpose.PRODUCT_IMAGE, true);
        var created = write(seller, "POST", "/products", """
                {"title":"Withdrawn review","description":"First edition","price_cents":100,
                 "category_ids":["%s"],"image_file_ids":["%d"]}
                """.formatted(category, firstImage), key(), 201);
        String path = "/products/" + text(created, "id");
        String oldAudit = text(created.path("pending_review"), "audit_id");
        write(seller, "POST", path + "/withdrawal", version(created), key(), 200);
        var withdrawn = get(seller, path, 200);
        assertThat(withdrawn.at("/permissions/can_submit_review").asBoolean()).isTrue();
        var edited = write(seller, "PATCH", path, """
                {"expected_version":%d,"description":"Second edition","image_file_ids":["%d"]}
                """.formatted(withdrawn.path("content_version").asInt(), nextImage), key(), 200);
        var history = get(seller, path + "/edit-history", 200).at("/items/0");
        assertThat(history.at("/before_content/image_file_ids/0").asLong()).isEqualTo(firstImage);
        assertThat(history.at("/after_content/image_file_ids/0").asLong()).isEqualTo(nextImage);
        var resubmitted = write(seller, "POST", path + "/review-submissions", version(edited), key(), 201);
        assertThat(text(resubmitted, "audit_id")).isNotEqualTo(oldAudit);
        assertThat(db.sql("select status from product_audit where audit_id = ?")
                .param(Long.parseLong(oldAudit)).query(String.class).single()).isEqualTo("withdrawn");
    }

    @Test
    void managementStatisticsUseTradeResultTimeAndKeepCurrentCountsIndependentOfRange() throws Exception {
        var manager = login("statistics", true);
        var buyer = login("statistics-buyer", false);
        String path = "/management/statistics";
        get(buyer, path + "?time_scope=all", 403);
        get(manager, path, 422);
        get(manager, path + "?time_scope=all&start_at=2026-10-01T00:00:00Z", 422);
        get(manager, path + "?time_scope=range&start_at=2026-10-01T00:00:00Z", 422);
        get(manager, path + "?time_scope=range&start_at=2026-10-02T00:00:00Z&end_at=2026-10-01T00:00:00Z", 422);

        String range = path + "?time_scope=range&start_at=2026-10-03T00:00:00Z&end_at=2026-10-04T00:00:00Z";
        var before = get(manager, range, 200);
        long buyerId = buyer.account().id();
        long sellerId = manager.account().id();
        try {
            db.sql("""
                    insert into trade(product_id, buyer_id, seller_id, status, terminal_reason, close_reason,
                                      requested_at, ended_at, created_at, updated_at)
                    select 50000000 + n, :buyer, :seller, status, terminal_reason, close_reason,
                           '2026-09-01T00:00:00Z', ended_at, '2026-09-01T00:00:00Z', '2026-11-05T00:00:00Z'
                    from (values
                        (1, 'completed', 'completed', null, timestamptz '2026-10-03T00:00:00Z'),
                        (2, 'completed', 'completed', null, timestamptz '2026-10-04T00:00:00Z'),
                        (3, 'terminated', 'cancelled', null, timestamptz '2026-10-03T02:00:00Z'),
                        (4, 'disputed', null, null, null),
                        (5, 'closed', null, 'other_user_locked', null),
                        (6, 'rejected', null, null, null),
                        (7, 'withdrawn', null, null, null)
                    ) as facts(n, status, terminal_reason, close_reason, ended_at)
                    """).param("buyer", buyerId).param("seller", sellerId).update();
            var selected = get(manager, range, 200);
            var all = get(manager, path + "?time_scope=all", 200);
            assertThat(selected.path("completed_in_selection").asLong())
                    .isEqualTo(before.path("completed_in_selection").asLong() + 1);
            assertThat(all.path("completed_in_selection").asLong()).isEqualTo(all.path("trades").path("completed").asLong());
            assertThat(all.path("selection").path("start_at").isNull()).isTrue();
            assertThat(all.path("selection").path("end_at").isNull()).isTrue();
            for (String group : List.of("accounts", "products_by_state", "pending", "trades")) {
                assertThat(selected.path(group)).isEqualTo(all.path(group));
            }
            assertThat(selected.path("trades").path("completed").asLong())
                    .isEqualTo(before.path("trades").path("completed").asLong() + 2);
            assertThat(selected.path("trades").path("terminated").asLong())
                    .isEqualTo(before.path("trades").path("terminated").asLong() + 1);
            assertThat(selected.path("trades").path("disputed").asLong())
                    .isEqualTo(before.path("trades").path("disputed").asLong() + 1);
            assertThat(selected.path("as_of").isString()).isTrue();

            db.sql("update account set role = 'user' where account_id = ?").param(sellerId).update();
            get(manager, path + "?time_scope=all", 403);
        } finally {
            db.sql("delete from trade where buyer_id = ? and seller_id = ?")
                    .param(buyerId).param(sellerId).update();
        }
    }

    private static long uploadedImage(long owner, FilePurpose purpose, boolean verified) {
        var now = Instant.now().minusSeconds(1);
        var registry = app.getBean(FileRegistry.class);
        var location = new OssFileObjects.Location(OSS_BUCKET, OSS_PREFIX + "/" + purpose.value() + "/" + UUID.randomUUID());
        long fileId = registry.register(new UploadRegistration.Draft(owner, purpose, null, location, 150, "image/png",
                "s2-fixture", now, now.plusSeconds(60), now.plusSeconds(300))).fileId();
        FILE_IDS.add(fileId);
        if (verified) {
            registry.markVerified(fileId, owner, "s2-test-etag", new VerifiedContent(150, "image/png"));
        }
        return fileId;
    }

    private static String avatar(long id) {
        return "{\"avatar_file_id\":\"" + id + "\"}";
    }

    private static List<Long> avatarReferences(long accountId) {
        return db.sql("""
                        SELECT file_id FROM file_reference
                        WHERE target_type = 'account' AND target_id = ? AND slot = 'avatar'
                        """)
                .param(accountId).query(Long.class).list();
    }

    private static String createCategory(SessionService.Issued manager, String name) {
        var auditContext = new AuditContext(new ExecutionContext(UUID.randomUUID(),
                ExecutionContext.ActorKind.ACCOUNT, Long.toString(manager.account().id()), UUID.randomUUID(), null,
                1L, "s2-review-it"), UUID.randomUUID());
        return app.getBean(CategoryService.class).create(manager.account().id(), name, auditContext).id();
    }

    private static SessionService.Issued login(String name, boolean manager) {        var email = name + "-" + RUN + "@s2-review.example";
        var digest = app.getBean(PasswordHasher.class).hash(PASSWORD);
        var account = app.getBean(AccountRepository.class).save(new Account(email, name, digest, Instant.now()));
        ACCOUNT_IDS.add(account.id());
        if (manager) {
            db.sql("UPDATE account SET role = 'manager' WHERE account_id = ?").param(account.id()).update();
        }
        var issued = app.getBean(AccountService.class).login(email, PASSWORD);
        SESSIONS.add(issued);
        return issued;
    }

    private static void deleteOwnedData(long owner) {
        String products = "SELECT product_id FROM product WHERE seller_account_id = ?";
        String cases = "SELECT case_id FROM product_audit WHERE product_id IN (" + products + ")";
        var caseIds = db.sql(cases).param(owner).query(Long.class).list();
        for (String table : List.of("product_favorite", "product_category", "product_edit_history",
                "category_application", "product_audit")) {
            db.sql("DELETE FROM " + table + " WHERE product_id IN (" + products + ")").param(owner).update();
        }
        for (long caseId : caseIds) {
            db.sql("DELETE FROM moderation_case_action WHERE case_id = ?").param(caseId).update();
            db.sql("DELETE FROM moderation_case WHERE id = ?").param(caseId).update();
        }
        db.sql("DELETE FROM product WHERE seller_account_id = ?").param(owner).update();
        db.sql("DELETE FROM notification WHERE recipient_account_id = ?").param(owner).update();
        db.sql("DELETE FROM operation_record WHERE actor_kind = 'account' AND actor_id = ?")
                .param(Long.toString(owner)).update();
        db.sql("DELETE FROM audit_record WHERE actor_kind = 'account' AND actor_id = ?")
                .param(Long.toString(owner)).update();
    }

    private static JsonNode get(SessionService.Issued session, String path, int expected) throws Exception {
        return send(request(session, path).GET(), expected);
    }

    private static JsonNode write(SessionService.Issued session, String method, String path,
                                  String body, String idempotencyKey, int expected) throws Exception {
        var request = request(session, path)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.csrfToken())
                .header("Idempotency-Key", idempotencyKey)
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body));
        return send(request, expected);
    }

    private static HttpRequest.Builder request(SessionService.Issued session, String path) {
        return HttpRequest.newBuilder(URI.create(baseUrl + "/api/v1" + path))
                .timeout(Duration.ofSeconds(10))
                .header("Cookie", AccountCookies.SESSION + "=" + session.token());
    }

    private static JsonNode send(HttpRequest.Builder request, int expected) throws Exception {
        var response = http.send(request.build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as("HTTP %s response: %s", request.build().uri().getPath(), response.body())
                .isEqualTo(expected);
        return json.readTree(response.body());
    }

    private static String text(JsonNode object, String property) {
        assertThat(object.path(property).asText()).as("field %s in %s", property, object).isNotBlank();
        return object.path(property).asText();
    }

    private static String version(JsonNode product) {
        return "{\"expected_version\":" + product.path("content_version").asInt() + "}";
    }

    private static String key() {
        return UUID.randomUUID().toString();
    }
}
