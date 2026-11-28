package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/** Account and product subject enforcement across direct, comment and trade case targets. */
class SubjectEnforcementHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;
    private static Session manager;
    private static Session reporter;
    private static Session seller;
    private static Session buyer;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("subject-enforcement");
        manager = http.account("subject-manager", "manager");
        reporter = http.account("subject-reporter", "user");
        seller = http.account("subject-seller", "user");
        buyer = http.account("subject-buyer", "user");
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void accountAndProductRestrictionsCanBeAppliedAndLiftedInOneCase() throws Exception {
        long product = publicProduct("Combined " + RUN);
        long caseId = report(manager, """
                {"target":{"target_type":"account","target_id":"%d"},"reason":"account enforcement"}
                """.formatted(http.accountId(seller)), 201);
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);

        var decided = http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"violation","reason":"test combined restrictions","basis_refs":[],
                 "enforcements":[
                   {"action":"restrict_account","target_type":"account","target_id":"%d"},
                   {"action":"lift_account_restriction","target_type":"account","target_id":"%d"},
                   {"action":"withdraw_public_access","target_type":"product","target_id":"%d"},
                   {"action":"restore_display","target_type":"product","target_id":"%d"}]}
                """.formatted(http.accountId(seller), http.accountId(seller), product, product), 201);
        assertThat(decided.path("enforcements").size()).isEqualTo(4);
        assertThat(http.get(buyer, "/products/" + product, 200).path("lifecycle_state").asString())
                .isEqualTo("public");
        assertThat(http.get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean())
                .isFalse();
    }

    @Test
    void commentAndTradeTargetsResolveTheirRelatedProductForWithdrawalAndRestore() throws Exception {
        long product = publicProduct("Related " + RUN);
        long comment = http.post(buyer, "/products/" + product + "/comments",
                "{\"body\":\"reported comment\"}", 201).path("id").asLong();
        long commentCase = report(reporter, """
                {"target":{"target_type":"comment","target_id":"%d"},"reason":"comment enforcement"}
                """.formatted(comment), 201);
        http.post(manager, "/admin/cases/" + commentCase + "/claim", null, 200);
        var commentDecision = http.post(manager, "/admin/cases/" + commentCase + "/decisions", """
                {"decision_kind":"violation","reason":"comment product restriction","basis_refs":[],
                 "enforcements":[
                   {"action":"withdraw_public_access","target_type":"product","target_id":"%d"},
                   {"action":"restore_display","target_type":"product","target_id":"%d"}]}
                """.formatted(product, product), 201);
        assertThat(commentDecision.path("enforcements").size()).isEqualTo(2);

        long trade = http.db.sql("""
                insert into trade (product_id, buyer_id, seller_id, status, requested_at, responded_at,
                                   created_at, updated_at)
                values (?, ?, ?, 'in_progress', now(), now(), now(), now()) returning id
                """).param(product).param(http.accountId(buyer)).param(http.accountId(seller))
                .query(Long.class).single();
        http.db.sql("insert into trade_conversation (trade_id, created_at) values (?, now())")
                .param(trade).update();
        long tradeCase = report(buyer, """
                {"target":{"target_type":"trade","target_id":"%d"},"reason":"trade enforcement"}
                """.formatted(trade), 201);
        http.post(manager, "/admin/cases/" + tradeCase + "/claim", null, 200);
        var tradeDecision = http.post(manager, "/admin/cases/" + tradeCase + "/decisions", """
                {"decision_kind":"violation","reason":"trade product restriction","basis_refs":[],
                 "enforcements":[
                   {"action":"withdraw_public_access","target_type":"product","target_id":"%d"},
                   {"action":"restore_display","target_type":"product","target_id":"%d"}]}
                """.formatted(product, product), 201);
        assertThat(tradeDecision.path("enforcements").size()).isEqualTo(2);
        assertThat(http.get(buyer, "/products/" + product, 200).path("lifecycle_state").asString())
                .isEqualTo("public");
    }

    @Test
    void missingRestrictionsAndUnrelatedProductsAreRejected() throws Exception {
        long product = publicProduct("Missing restriction " + RUN);
        long caseId = report(reporter, """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"restore without restriction"}
                """.formatted(product), 201);
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        var restore = http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"no_action","reason":"nothing active","basis_refs":[],
                 "enforcements":[{"action":"restore_display","target_type":"product","target_id":"%d"}]}
                """.formatted(product), 409);
        assertThat(restore.path("error").path("code").asString()).isEqualTo("RESTRICTION_NOT_ACTIVE");

        long unrelated = publicProduct("Unrelated " + RUN);
        long otherCase = report(buyer, """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"wrong product"}
                """.formatted(product), 201);
        http.post(manager, "/admin/cases/" + otherCase + "/claim", null, 200);
        http.post(manager, "/admin/cases/" + otherCase + "/decisions", """
                {"decision_kind":"violation","reason":"wrong product target","basis_refs":[],
                 "enforcements":[{"action":"withdraw_public_access","target_type":"product",
                                  "target_id":"%d"}]}
                """.formatted(unrelated), 403);

        http.post(manager, "/admin/cases/" + otherCase + "/decisions", """
                {"decision_kind":"violation","reason":"wrong action target","basis_refs":[],
                 "enforcements":[{"action":"restrict_account","target_type":"product",
                                  "target_id":"%d"}]}
                """.formatted(product), 422);
    }

    private long report(Session account, String body, int status) throws Exception {
        return http.post(account, "/cases", body, status).path("case_id").asLong();
    }

    private long publicProduct(String title) {
        return http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 1000, 'public') returning product_id
                """).param(http.accountId(seller)).param(title).query(Long.class).single();
    }
}
