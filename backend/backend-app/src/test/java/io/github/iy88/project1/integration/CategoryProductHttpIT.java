package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.category.application.BannedScopeService;
import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

/**
 * Category administration, banned-scope maintenance and the product lifecycle through the normal
 * HTTP entry points, using the isolated PostgreSQL/Redis fixture and real application services.
 */
class CategoryProductHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;
    private static Session manager;
    private static Session seller;
    private static Session buyer;
    private static Session other;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("category-product");
        manager = http.account("cat-manager", "manager");
        seller = http.account("cat-seller", "user");
        buyer = http.account("cat-buyer", "user");
        other = http.account("cat-other", "user");
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void categoryAdministrationCoversConflictsAliasesDisableAndDeletion() throws Exception {
        http.get(manager, "/admin/categories?page=0", 422);
        http.get(manager, "/admin/categories?page_size=101", 422);
        http.get(buyer, "/admin/categories", 403);

        var created = http.post(manager, "/admin/categories",
                "{\"name\":\"Category " + RUN + "\"}", 201);
        long categoryId = Long.parseLong(created.path("id").asString());
        assertThat(created.path("state").asString()).isEqualTo("active");
        assertThat(created.path("main_name").asString()).isEqualTo("Category " + RUN);

        http.post(manager, "/admin/categories", "{\"name\":\"Category " + RUN + "\"}", 409);
        http.post(manager, "/admin/categories", "{\"name\":\"   \"}", 422);
        http.post(manager, "/admin/categories", "{\"name\":\"" + "x".repeat(51) + "\"}", 422);

        var renamed = http.patch(manager, "/admin/categories/" + categoryId,
                "{\"main_name\":\"Renamed " + RUN + "\"}", 200);
        // The write response may still expose a pre-update persistence-context projection.
        assertThat(http.db.sql("""
                select name from category_name
                 where category_id = ? and name_kind = 'main' and deactivated_at is null
                """).param(categoryId).query(String.class).single()).isEqualTo("Renamed " + RUN);
        assertThat(http.patch(manager, "/admin/categories/" + categoryId,
                "{\"main_name\":\"Renamed " + RUN + "\"}", 200).path("state").asString())
                .isEqualTo("active");

        var alias = http.post(manager, "/admin/categories/" + categoryId + "/aliases",
                "{\"name\":\"Alias " + RUN + "\"}", 201);
        long aliasId = Long.parseLong(alias.path("category_name_id").asString());
        http.post(manager, "/admin/categories/" + categoryId + "/aliases",
                "{\"name\":\"Alias " + RUN + "\"}", 409);
        http.delete(manager, "/admin/categories/" + categoryId + "/aliases/" + aliasId, 204);
        http.delete(manager, "/admin/categories/" + categoryId + "/aliases/" + aliasId, 204);
        http.delete(manager, "/admin/categories/" + categoryId + "/aliases/999999999", 404);

        var activeAlias = http.post(manager, "/admin/categories/" + categoryId + "/aliases",
                "{\"name\":\"AliasTwo " + RUN + "\"}", 201);
        long activeAliasId = Long.parseLong(activeAlias.path("category_name_id").asString());
        long mainNameId = http.db.sql("""
                select category_name_id from category_name
                 where category_id = ? and name_kind = 'main' and deactivated_at is null
                """).param(categoryId).query(Long.class).single();
        http.delete(manager, "/admin/categories/" + categoryId + "/aliases/" + mainNameId, 409);

        var disabled = http.post(manager, "/admin/categories/" + categoryId + "/disable", null, 200);
        assertThat(disabled.path("state").asString()).isEqualTo("disabled");
        assertThat(http.post(manager, "/admin/categories/" + categoryId + "/disable", null, 200)
                .path("state").asString()).isEqualTo("disabled");
        var publicView = http.get(buyer, "/categories", 200);
        assertThat(ids(publicView.path("items"))).doesNotContain(Long.toString(categoryId));
        http.delete(manager, "/admin/categories/" + categoryId + "/aliases/" + activeAliasId, 204,
                http.key());

        http.delete(manager, "/admin/categories/" + categoryId, 204);
        http.delete(manager, "/admin/categories/" + categoryId, 204);
        http.patch(manager, "/admin/categories/" + categoryId, "{\"main_name\":\"Gone\"}", 404);
        http.patch(manager, "/admin/categories/not-a-number", "{\"main_name\":\"Gone\"}", 422);

        var publicCategory = http.post(manager, "/admin/categories",
                "{\"name\":\"Public " + RUN + "\"}", 201);
        long publicCategoryId = Long.parseLong(publicCategory.path("id").asString());
        assertThat(ids(http.get(buyer, "/categories", 200).path("items")))
                .contains(Long.toString(publicCategoryId));

        var product = http.post(seller, "/products", """
                {"title":"Category guarded %s","description":"category guard","price_cents":100,
                 "category_ids":["%d"]}
                """.formatted(RUN, publicCategoryId), 201);
        long productId = Long.parseLong(product.path("id").asString());
        http.delete(manager, "/admin/categories/" + publicCategoryId, 409);
        http.get(manager, "/admin/categories?page=1&page_size=2", 200);
        http.get(seller, "/products/" + productId, 200);
    }

    @Test
    void bannedScopeMaintenanceValidatesGroupsAndProtectsTheRequiredScope() throws Exception {
        var initial = http.get(buyer, "/banned-items", 200);
        assertThat(initial.path("groups").isArray()).isTrue();
        var existing = flatten(initial);
        http.post(manager, "/admin/banned-items", "{\"group\":\"other\",\"content\":\"x\",\"display_order\":1}",
                201);
        http.post(buyer, "/admin/banned-items", "{\"group\":\"other\",\"content\":\"x\",\"display_order\":1}",
                403);
        http.post(manager, "/admin/banned-items", "{\"group\":\"unknown\",\"content\":\"x\",\"display_order\":1}",
                422);
        http.post(manager, "/admin/banned-items", "{\"group\":\"other\",\"content\":\"  \",\"display_order\":1}",
                422);
        http.post(manager, "/admin/banned-items", "{\"group\":\"other\",\"content\":\"x\",\"display_order\":-1}",
                422);
        http.post(manager, "/admin/banned-items", "{\"group\":\"other\",\"content\":\"x\"}", 422);

        var item = http.post(manager, "/admin/banned-items",
                "{\"group\":\"other\",\"content\":\"Other " + RUN + "\",\"display_order\":9}", 201);
        long itemId = Long.parseLong(item.path("item").path("id").asString());
        var updated = http.patch(manager, "/admin/banned-items/" + itemId,
                "{\"group\":\"other\",\"content\":\"Updated " + RUN + "\",\"display_order\":10}", 200);
        assertThat(updated.path("item").path("content").asString()).isEqualTo("Updated " + RUN);
        http.patch(manager, "/admin/banned-items/999999999",
                "{\"group\":\"other\",\"content\":\"x\",\"display_order\":1}", 422);
        http.patch(manager, "/admin/banned-items/not-a-number",
                "{\"group\":\"other\",\"content\":\"x\",\"display_order\":1}", 422);
        http.put(manager, "/admin/banned-items", "{\"items\":[]}", 422);
        http.put(manager, "/admin/banned-items",
                "{\"items\":[{\"group\":\"other\",\"content\":\"x\",\"display_order\":1}]}", 422);

        // The seeded fixture intentionally has only the optional group, so a full replacement
        // is exercised at the application-service layer inside a transaction that is rolled back.
        var inputs = new ArrayList<BannedScopeService.Input>();
        for (var entry : existing) {
            inputs.add(new BannedScopeService.Input(entry.id(), entry.group(), entry.content(),
                    entry.displayOrder()));
        }
        for (var group : List.of("legal_prohibited", "dangerous_controlled", "live_animals",
                "medicine_device", "account_virtual", "service_promotion")) {
            inputs.add(new BannedScopeService.Input(null, group, group + "-" + RUN, 50));
        }
        new TransactionTemplate(http.app.getBean(PlatformTransactionManager.class))
                .executeWithoutResult(status -> {
                    var replaced = http.app.getBean(BannedScopeService.class)
                            .replace(http.accountId(manager), inputs);
                    assertThat(replaced.groups()).hasSizeGreaterThanOrEqualTo(7);
                    status.setRollbackOnly();
                });
        var beforeReplace = flatten(http.get(buyer, "/banned-items", 200));
        assertThat(flatten(http.get(buyer, "/banned-items", 200))).hasSameSizeAs(beforeReplace);
        http.delete(manager, "/admin/banned-items/" + itemId, 200);
    }

    @Test
    void productLifecycleReviewInteractionsAndAccountResources() throws Exception {
        var category = http.post(manager, "/admin/categories",
                "{\"name\":\"Shelf " + RUN + "\"}", 201);
        long categoryId = Long.parseLong(category.path("id").asString());
        var proposedName = "Proposed " + RUN;
        var created = http.post(seller, "/products", """
                {"title":"Lifecycle %s","description":"first description","price_cents":1500,
                 "category_ids":["%d"],"category_application":{"proposed_name":"%s"}}
                """.formatted(RUN, categoryId, proposedName), 201);
        long productId = Long.parseLong(created.path("id").asString());
        assertThat(created.path("lifecycle_state").asString()).isEqualTo("pending_review");
        assertThat(created.path("category_application").path("status").asString()).isEqualTo("pending");
        assertThat(created.path("permissions").path("can_edit").asBoolean()).isTrue();
        int version = created.path("content_version").asInt();

        http.get(buyer, "/products/" + productId, 404);
        assertThat(http.get(buyer, "/products?keyword=Lifecycle%20" + RUN, 200).path("total").asLong()).isZero();
        http.get(seller, "/products/" + productId, 200);

        http.patch(seller, "/products/" + productId, "{\"expected_version\":" + version + "}", 422);
        http.patch(seller, "/products/" + productId,
                "{\"title\":\"Wrong version\",\"expected_version\":999}", 409);
        http.patch(seller, "/products/" + productId,
                "{\"price_cents\":-1,\"expected_version\":" + version + "}", 422);
        var edited = http.patch(seller, "/products/" + productId, """
                {"title":"Lifecycle %s edited","price_cents":1700,"expected_version":%d}
                """.formatted(RUN, version), 200);
        assertThat(edited.path("price_cents").asLong()).isEqualTo(1700);
        version = edited.path("content_version").asInt();

        http.post(seller, "/products/" + productId + "/category-applications",
                "{\"proposed_name\":\"Another " + RUN + "\"}", 409);
        http.delete(seller, "/products/" + productId + "/category-application", 204);
        var application = http.post(seller, "/products/" + productId + "/category-applications",
                "{\"proposed_name\":\"" + proposedName + "\"}", 201);
        assertThat(application.path("status").asString()).isEqualTo("pending");
        assertThat(http.delete(seller, "/products/" + productId + "/category-application", 204).isNull())
                .isTrue();
        http.delete(seller, "/products/" + productId + "/category-application", 409);
        http.post(seller, "/products/" + productId + "/category-applications",
                "{\"proposed_name\":\"" + proposedName + "\"}", 201);

        var detail = http.get(seller, "/products/" + productId, 200);
        var pending = detail.path("pending_review");
        long caseId = pending.path("case_id").asLong();
        long auditId = pending.path("audit_id").asLong();
        http.get(buyer, "/admin/product-reviews/" + auditId, 404);
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        http.get(manager, "/admin/product-reviews/" + auditId, 200);
        var bannedIds = flatten(http.get(manager, "/banned-items", 200)).stream()
                .map(Entry::id).limit(1).toList();
        var bannedJson = bannedIds.isEmpty() ? "[]" : "[\"" + bannedIds.getFirst() + "\"]";
        var decision = """
                {"decision":"approved","reason":"content ok",
                 "category_application_decision":"approved",
                 "banned_item_ids":%s}
                """.formatted(bannedJson);
        http.post(manager, "/admin/product-reviews/" + auditId + "/decision", decision, 200);
        var approved = http.get(buyer, "/products/" + productId, 200);
        assertThat(approved.path("lifecycle_state").asString()).isEqualTo("public");
        version = http.get(seller, "/products/" + productId, 200).path("content_version").asInt();
        assertThat(http.get(buyer, "/products?keyword=Lifecycle%20" + RUN, 200).path("total").asLong())
                .isEqualTo(1);
        http.get(buyer, "/products/" + productId + "/edit-history", 404);
        var sellerHistory = http.get(seller, "/products/" + productId + "/edit-history?page=1&page_size=5", 200);
        assertThat(sellerHistory.path("items").size()).isGreaterThanOrEqualTo(1);
        http.get(seller, "/products/" + productId + "/edit-history?page=0", 422);
        http.get(seller, "/products/" + productId + "/edit-history?trade_id=1&case_id=2", 422);

        var offShelf = http.post(seller, "/products/" + productId + "/off-shelf",
                "{\"expected_version\":" + version + "}", 200);
        assertThat(offShelf.path("product").path("lifecycle_state").asString()).isEqualTo("off_shelf");
        version = offShelf.path("product").path("content_version").asInt();
        http.get(buyer, "/products/" + productId, 404);
        http.post(seller, "/products/" + productId + "/on-shelf",
                "{\"expected_version\":999}", 409);
        var onShelf = http.post(seller, "/products/" + productId + "/on-shelf",
                "{\"expected_version\":" + version + "}", 200);
        assertThat(onShelf.path("lifecycle_state").asString()).isEqualTo("public");
        version = onShelf.path("content_version").asInt();
        http.post(seller, "/products/" + productId + "/on-shelf",
                "{\"expected_version\":" + version + "}", 409);

        var comment = http.post(buyer, "/products/" + productId + "/comments",
                "{\"body\":\"Is it available?\"}", 201);
        long commentId = Long.parseLong(comment.path("id").asString());
        http.post(buyer, "/products/" + productId + "/comments/" + commentId + "/replies",
                "{\"body\":\"not seller\"}", 403);
        var reply = http.post(seller, "/products/" + productId + "/comments/" + commentId + "/replies",
                "{\"body\":\"Yes, it is.\"}", 201);
        long replyId = Long.parseLong(reply.path("id").asString());
        assertThat(http.get(buyer, "/products/" + productId + "/comments?page=1&page_size=10", 200)
                .path("items").size()).isEqualTo(1);
        http.delete(other, "/products/" + productId + "/comments/" + replyId, 403);
        http.delete(seller, "/products/" + productId + "/comments/" + replyId, 204);
        http.delete(seller, "/products/" + productId + "/comments/" + replyId, 204);

        var favorite = http.put(buyer, "/me/favorites/" + productId, null, 200);
        assertThat(favorite.path("favorited").asBoolean()).isTrue();
        assertThat(http.get(buyer, "/me/favorites/" + productId, 200).path("valid").asBoolean()).isTrue();
        assertThat(http.get(buyer, "/me/favorites?page=1&page_size=10", 200).path("items").size())
                .isGreaterThanOrEqualTo(1);
        assertThat(http.get(buyer, "/account/resources?kind=favorite&page=1&page_size=10", 200)
                .path("items").size()).isGreaterThanOrEqualTo(1);
        http.get(buyer, "/account/resources?kind=favorite&role=buyer", 422);
        http.delete(buyer, "/me/favorites/" + productId, 204);

        assertThat(http.get(seller, "/account/resources?kind=product&state=public", 200)
                .path("items").size()).isGreaterThanOrEqualTo(1);
        http.get(seller, "/account/resources?kind=product&state=bad", 422);
        http.get(seller, "/account/resources?kind=product&role=buyer", 422);
        http.get(seller, "/account/resources", 422);
        http.get(seller, "/account/resources?kind=trade&direction=bad", 422);
        http.get(seller, "/account/resources?kind=evaluation&state=bad", 422);
        http.get(seller, "/account/resources?kind=report&role=buyer", 422);
        http.get(seller, "/account/resources?kind=trade&page=0", 422);
        http.get(seller, "/account/resources?kind=report&direction=bad", 422);
        http.get(seller, "/account/todos?kind=bad", 422);
        http.get(seller, "/account/overview", 200);
        http.get(seller, "/account/todos?page=1&page_size=5", 200);
        http.get(seller, "/account/todos?kind=inquiry_response", 200);
    }

    @Test
    void rejectedReviewResubmissionWithdrawalAndSearchValidation() throws Exception {
        var category = http.post(manager, "/admin/categories", "{\"name\":\"Edge " + RUN + "\"}", 201);
        long categoryId = Long.parseLong(category.path("id").asString());

        http.post(seller, "/products", "{}", 422);
        http.post(seller, "/products", """
                {"title":"%s","description":"d","price_cents":100,"category_ids":["%d"]}
                """.formatted("x".repeat(101), categoryId), 422);
        http.post(seller, "/products", """
                {"title":"Valid %s","description":"%s","price_cents":100,"category_ids":["%d"]}
                """.formatted(RUN, "d".repeat(5001), categoryId), 422);
        http.post(seller, "/products", """
                {"title":"Valid %s","description":"d","price_cents":-1,"category_ids":["%d"]}
                """.formatted(RUN, categoryId), 422);
        http.post(seller, "/products", """
                {"title":"Valid %s","description":"d","price_cents":100}
                """.formatted(RUN), 422);
        http.post(seller, "/products", """
                {"title":"Valid %s","description":"d","price_cents":100,"category_ids":["999999999"]}
                """.formatted(RUN), 422);
        http.post(seller, "/products", """
                {"title":"Valid %s","description":"d","price_cents":100,"category_ids":["bad"]}
                """.formatted(RUN), 422);

        var created = http.post(seller, "/products", """
                {"title":"Rejected %s","description":"d","price_cents":100,"category_ids":["%d"],
                 "category_application":{"proposed_name":"Rejected category %s"}}
                """.formatted(RUN, categoryId, RUN), 201);
        long productId = Long.parseLong(created.path("id").asString());
        int version = created.path("content_version").asInt();
        var detail = http.get(seller, "/products/" + productId, 200);
        long caseId = detail.at("/pending_review/case_id").asLong();
        long auditId = detail.at("/pending_review/audit_id").asLong();
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        http.post(manager, "/admin/product-reviews/" + auditId + "/decision", """
                {"decision":"rejected","reason":"not acceptable",
                 "category_application_decision":"rejected",
                 "category_application_reason":"name not acceptable"}
                """, 200);
        var rejected = http.get(seller, "/products/" + productId, 200);
        assertThat(rejected.path("lifecycle_state").asString()).isEqualTo("review_rejected");
        assertThat(rejected.at("/latest_review/status").asString()).isEqualTo("rejected");
        version = rejected.path("content_version").asInt();

        var edited = http.patch(seller, "/products/" + productId, """
                {"title":"Rejected %s edited","category_ids":["%d"],"expected_version":%d}
                """.formatted(RUN, categoryId, version), 200);
        version = edited.path("content_version").asInt();
        var resubmitted = http.post(seller, "/products/" + productId + "/review-submissions",
                "{\"expected_version\":" + version + "}", 201);
        version = resubmitted.path("content_version").asInt();
        var withdrawn = http.post(seller, "/products/" + productId + "/withdrawal",
                "{\"expected_version\":" + version + "}", 200);
        assertThat(withdrawn.path("lifecycle_state").asString()).isEqualTo("off_shelf");
        http.post(seller, "/products/" + productId + "/withdrawal",
                "{\"expected_version\":" + version + "}", 409);

        http.get(seller, "/products?page=0", 422);
        http.get(seller, "/products?page_size=101", 422);
        http.get(seller, "/products?min_price_cents=-1", 422);
        http.get(seller, "/products?max_price_cents=-1", 422);
        http.get(seller, "/products?min_price_cents=200&max_price_cents=100", 422);
        http.get(seller, "/products?category_ids=bad", 422);
        http.get(seller, "/products?keyword=Rejected&min_price_cents=0&max_price_cents=1000", 200);
        http.get(seller, "/account/resources?kind=product&state=review_rejected", 200);
        http.get(seller, "/account/resources?kind=product&state=", 200);
        http.get(seller, "/me/favorites/999999999", 404);
        http.put(seller, "/me/favorites/999999999", null, 404);
        http.db.sql("update product set lifecycle_state = 'public' where product_id = ?")
                .param(productId).update();
        http.post(seller, "/products/" + productId + "/comments", "{\"body\":\"\"}", 422);
        http.post(seller, "/products/" + productId + "/comments",
                "{\"body\":\"" + "x".repeat(501) + "\"}", 422);
        http.get(seller, "/products/" + productId + "/comments?page=0", 422);
        http.get(seller, "/products/" + productId + "/comments?page_size=101", 422);
        http.get(seller, "/products/" + productId + "/comments?anchor_comment_id=999999999", 200);
        http.get(seller, "/products/" + productId + "/comments?case_id=bad", 422);
    }

    @Test
    void reviewCategoryDecisionsAndAdminCorrectionCoverTheirBranches() throws Exception {
        var first = http.post(manager, "/admin/categories", "{\"name\":\"First " + RUN + "\"}", 201);
        var second = http.post(manager, "/admin/categories", "{\"name\":\"Second " + RUN + "\"}", 201);
        long firstId = Long.parseLong(first.path("id").asString());
        long secondId = Long.parseLong(second.path("id").asString());
        var created = http.post(seller, "/products", """
                {"title":"Review branches %s","description":"d","price_cents":100,
                 "category_ids":["%d"],"category_application":{"proposed_name":"First %s"}}
                """.formatted(RUN, firstId, RUN), 201);
        long productId = Long.parseLong(created.path("id").asString());
        var detail = http.get(seller, "/products/" + productId, 200);
        long caseId = detail.at("/pending_review/case_id").asLong();
        long auditId = detail.at("/pending_review/audit_id").asLong();
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        var path = "/admin/product-reviews/" + auditId + "/decision";
        http.post(manager, path, """
                {"decision":"approved","reason":"ok"}
                """, 422);
        http.post(manager, path, """
                {"decision":"approved","reason":"ok","category_application_decision":"rejected"}
                """, 422);
        http.post(manager, path, """
                {"decision":"approved","reason":"ok","category_application_decision":"approved",
                 "banned_item_ids":["999999999"]}
                """, 422);
        http.post(manager, path, """
                {"decision":"approved","reason":"ok","category_application_decision":"approved",
                 "banned_item_ids":[]}
                """, 200);
        http.post(manager, path, """
                {"decision":"approved","reason":"again","category_application_decision":"approved"}
                """, 409);

        var correctionReport = http.post(buyer, "/cases", """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"wrong category"}
                """.formatted(productId), 201);
        long correctionCase = correctionReport.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + correctionCase + "/claim", null, 200);
        var correctionPath = "/admin/products/" + productId + "/category-correction";
        http.post(manager, correctionPath, """
                {"category_ids":["%d"],"reason":"corrected"}
                """.formatted(secondId), 403);
        http.post(manager, correctionPath, """
                {"category_ids":["%d"],"reason":"corrected","basis_ref":{"type":"bad","id":"%d"}}
                """.formatted(secondId, correctionCase), 422);
        http.post(manager, correctionPath, """
                {"category_ids":[],"reason":"corrected","basis_ref":{"type":"case","id":"%d"}}
                """.formatted(correctionCase), 422);
        var corrected = http.post(manager, correctionPath, """
                {"category_ids":["%d"],"reason":"corrected","basis_ref":{"type":"case","id":"%d"}}
                """.formatted(secondId, correctionCase), 200);
        assertThat(corrected.path("current_categories").isArray()).isTrue();
        http.post(manager, correctionPath, """
                {"category_ids":["%d"],"reason":"same","basis_ref":{"type":"case","id":"%d"}}
                """.formatted(secondId, correctionCase), 200);
        http.post(buyer, correctionPath, """
                {"category_ids":["%d"],"reason":"denied","basis_ref":{"type":"case","id":"%d"}}
                """.formatted(secondId, correctionCase), 403);
        http.get(manager, "/products/" + productId + "/edit-history?case_id=" + correctionCase
                + "&page=1&page_size=5", 200);
        http.get(buyer, "/products/" + productId + "/edit-history?case_id=" + correctionCase, 404);
    }

    private static JsonNode findCategory(JsonNode page, long categoryId) {
        for (var item : page.path("items")) {
            if (item.path("id").asString().equals(Long.toString(categoryId))) {
                return item;
            }
        }
        return page;
    }

    private static long currentMainNameId(JsonNode page, long categoryId) {
        for (var name : findCategory(page, categoryId).path("names")) {
            if ("main".equals(name.path("kind").asString()) && name.path("active").asBoolean()) {
                return name.path("category_name_id").asLong();
            }
        }
        return -1;
    }

    private static List<String> ids(JsonNode items) {
        var result = new ArrayList<String>();
        items.forEach(item -> result.add(item.path("id").asString()));
        return result;
    }

    private static List<Entry> flatten(JsonNode view) {
        var entries = new ArrayList<Entry>();
        for (var group : view.path("groups")) {
            for (var item : group.path("items")) {
                entries.add(new Entry(item.path("id").asString(), group.path("group").asString(),
                        item.path("content").asString(), item.path("display_order").asInt()));
            }
        }
        return entries;
    }

    private record Entry(String id, String group, String content, int displayOrder) {
    }
}
