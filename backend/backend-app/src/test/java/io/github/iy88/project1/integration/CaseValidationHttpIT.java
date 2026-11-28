package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/** Malformed case requests, viewpoint reads, evidence and notification projections. */
class CaseValidationHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;
    private static Session manager;
    private static Session reporter;
    private static Session seller;
    private static Session buyer;
    private static Session other;
    private static long product;
    private static long commentId;
    private static long chatId;
    private static long chatMessageId;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("case-validation");
        manager = http.account("valid-manager", "manager");
        reporter = http.account("valid-reporter", "user");
        seller = http.account("valid-seller", "user");
        buyer = http.account("valid-buyer", "user");
        other = http.account("valid-other", "user");
        product = http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 100, 'public') returning product_id
                """).param(http.accountId(seller)).param("Validation product " + RUN).query(Long.class).single();
        commentId = Long.parseLong(http.post(buyer, "/products/" + product + "/comments",
                "{\"body\":\"validation comment\"}", 201).path("id").asString());
        chatId = http.post(other, "/conversations/private",
                "{\"target_account_id\":\"" + http.accountId(buyer) + "\"}", 200)
                .path("conversation_id").asLong();
        chatMessageId = http.post(buyer, "/conversations/chat/" + chatId + "/messages",
                "{\"body\":\"validation message\"}", 201).path("message_id").asLong();
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void malformedReportsAndCaseOperationsAreRejectedWithoutSideEffects() throws Exception {
        http.post(buyer, "/cases", "{}", 422);
        http.post(buyer, "/cases", "{\"target\":{}}", 422);
        http.post(buyer, "/cases", "{\"target\":{\"target_type\":\"product\"}}", 422);
        http.post(buyer, "/cases",
                "{\"target\":{\"target_type\":\"account\",\"target_id\":\"%d\",\"source_product_id\":\"bad\"}}"
                        .formatted(http.accountId(seller)), 422);
        http.post(buyer, "/cases",
                "{\"target\":{\"target_type\":\"product\",\"target_id\":\"%d\"}}".formatted(product), 422);
        http.get(buyer, "/cases/not-a-number", 404);
        http.post(buyer, "/cases/not-a-number/supplements", "{\"note\":\"x\"}", 404);
        http.post(manager, "/admin/cases/not-a-number/claim", null, 404);
        http.writeWithoutKey(manager, "POST", "/admin/cases/1/claim", null, 422);

        long caseId = report(reporter, "product", Long.toString(product), null);
        http.post(reporter, "/cases/" + caseId + "/supplements", "{}", 422);
        http.post(reporter, "/cases/" + caseId + "/supplements",
                "{\"note\":\"x\",\"attachments\":[{\"file_id\":\"bad\"}]}", 422);
        http.post(reporter, "/cases/" + caseId + "/messages", """
                {"thread":{"conversation_kind":"bad","conversation_id":"1"},
                 "message_kind":"statement","body":"x"}
                """, 422);
        http.post(reporter, "/cases/" + caseId + "/messages", """
                {"thread":{"conversation_kind":"case","conversation_id":"1"},
                 "message_kind":"statement","body":"x"}
                """, 422);
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        http.post(manager, "/admin/cases/" + caseId + "/close", null, 409);
        http.post(manager, "/admin/cases/" + caseId + "/publish-result",
                "{\"public_summary\":\"x\",\"public_reason\":\"y\"}", 409);
        http.post(reporter, "/cases/" + caseId + "/messages", """
                {"thread":{"conversation_kind":"case","conversation_id":"1"},
                 "message_kind":"unsupported","body":"x"}
                """, 422);
        http.post(reporter, "/cases/" + caseId + "/messages", """
                {"message_kind":"statement","body":"x","basis_refs":[],"basis_ref":"case:1"}
                """, 422);
        http.post(reporter, "/cases/" + caseId + "/messages", """
                {"message_kind":"statement","body":"x","original_enforcement_id":"%s"}
                """.formatted("x".repeat(129)), 422);
        http.post(reporter, "/cases/" + caseId + "/messages",
                "{\"message_kind\":\"statement\",\"body\":\"x\",\"inquiry_action_id\":\"bad\"}", 422);
        http.post(reporter, "/cases/" + caseId + "/messages",
                "{\"message_kind\":\"appeal\",\"body\":\"x\"}", 409);
        http.post(manager, "/cases/" + caseId + "/messages",
                "{\"message_kind\":\"manager_reply\",\"body\":\"x\"}", 422);
        http.post(manager, "/cases/" + caseId + "/messages", """
                {"message_kind":"manager_reply","body":"x","appeal_action_id":"1",
                 "resolution":"unsupported"}
                """, 422);
        http.post(manager, "/cases/" + caseId + "/messages", """
                {"message_kind":"manager_reply","body":"x","appeal_action_id":"1","resolution":"adjust",
                 "basis_ref":"case:1"}
                """, 422);
        http.post(manager, "/cases/" + caseId + "/messages", """
                {"message_kind":"manager_reply","body":"x","appeal_action_id":"1","resolution":"revoke",
                 "basis_ref":"case:1","replacement_enforcements":[]}
                """, 422);
        http.post(manager, "/admin/cases/" + caseId + "/inquiries", "{}", 422);
        http.post(manager, "/admin/cases/" + caseId + "/inquiries",
                "{\"peer_account_id\":\"" + http.accountId(manager) + "\",\"scope_text\":\"x\"}", 422);
        http.post(manager, "/admin/cases/" + caseId + "/inquiries",
                "{\"peer_account_id\":\"" + http.accountId(reporter) + "\",\"scope_text\":\"x\"}", 422);
        http.post(manager, "/admin/cases/" + caseId + "/decisions", "{}", 422);
        http.post(manager, "/admin/cases/" + caseId + "/decisions",
                "{\"decision_kind\":\"bad\",\"reason\":\"x\",\"basis_refs\":[],\"enforcements\":[]}", 422);
        http.post(manager, "/admin/cases/" + caseId + "/decisions",
                "{\"decision_kind\":\"violation\",\"basis_refs\":[],\"enforcements\":[]}", 422);
        http.post(manager, "/admin/cases/" + caseId + "/decisions",
                "{\"decision_kind\":\"violation\",\"reason\":\"x\",\"basis_refs\":[],"
                        + "\"enforcements\":[{\"action\":\"bad\",\"target_type\":\"product\",\"target_id\":\"1\"}]}",
                422);
        http.post(manager, "/admin/cases/" + caseId + "/decisions",
                "{\"decision_kind\":\"violation\",\"reason\":\"x\",\"basis_refs\":[],"
                        + "\"enforcements\":[{\"action\":\"withdraw_public_access\","
                        + "\"target_type\":\"account\",\"target_id\":\"1\"}]}", 422);
        http.get(manager, "/admin/cases/" + caseId + "/evidence/not-a-number", 404);
        http.get(manager, "/admin/cases/" + caseId + "/evidence/999999999", 404);
        http.post(manager, "/admin/cases/" + caseId + "/evidence", "{\"message_id\":\"bad\"}", 422);
    }

    @Test
    void eachTargetTypeProducesAViewpointScopedDetailAndNotification() throws Exception {
        long productCase = report(other, "product", Long.toString(product), null);
        long accountCase = report(other, "account", Long.toString(http.accountId(seller)), Long.toString(product));
        long commentCase = report(other, "comment", Long.toString(commentId), null);
        long messageCase = reportMessage();
        for (long id : new long[]{productCase, accountCase, commentCase, messageCase}) {
            assertThat(http.get(other, "/cases/" + id, 200).path("case_id").asLong()).isEqualTo(id);
            http.get(buyer, "/cases/" + id, 404);
            http.post(manager, "/admin/cases/" + id + "/claim", null, 200);
            var detail = http.get(manager, "/cases/" + id, 200);
            assertThat(detail.path("case_status").asString()).isEqualTo("claimed");
            http.post(manager, "/admin/cases/" + id + "/decisions", """
                    {"decision_kind":"no_action","reason":"reviewed","basis_refs":[],"enforcements":[]}
                    """, 201);
            var decided = http.get(other, "/cases/" + id, 200);
            assertThat(decided.path("archived_at").isNull()).isTrue();
            http.post(manager, "/admin/cases/" + id + "/close", null, 200);
            http.post(manager, "/admin/cases/" + id + "/publish-result", """
                    {"public_summary":"summary","public_reason":"reason"}
                    """, 200);
            assertThat(http.get(other, "/case-results?target_type=product&target_id=" + product
                    + "&page=1&page_size=10", 200).path("items").isArray()).isTrue();
        }
        http.get(other, "/case-results", 200);
        http.get(other, "/case-results?target_type=product&page=1&page_size=10", 200);
        http.get(other, "/case-results?conversation_kind=chat&conversation_id=" + chatId, 200);
        http.get(other, "/case-results?conversation_kind=bad&conversation_id=bad", 422);
        http.get(other, "/case-results?page=0", 422);
        assertThat(http.get(other, "/account/notifications?page=1&page_size=50", 200)
                .path("total").asLong()).isGreaterThanOrEqualTo(1);
        assertThat(http.get(manager, "/account/notifications?audience=management&page=1&page_size=50", 200)
                .path("items").isArray()).isTrue();
        assertThat(http.get(seller, "/account/notifications?page=1&page_size=50", 200)
                .path("total").asLong()).isGreaterThanOrEqualTo(1);
    }

    private long report(Session session, String type, String id, String sourceProduct) throws Exception {
        var body = "{\"target\":{\"target_type\":\"" + type + "\",\"target_id\":\"" + id + "\""
                + (sourceProduct == null ? "" : ",\"source_product_id\":\"" + sourceProduct + "\"")
                + "},\"reason\":\"validation report\"}";
        return Long.parseLong(http.post(session, "/cases", body, 201).path("case_id").asString());
    }

    private long reportMessage() throws Exception {
        var body = """
                {"target":{"target_type":"message","target_id":"%d",
                           "conversation_kind":"chat","conversation_id":"%d"},
                 "reason":"message report"}
                """.formatted(chatMessageId, chatId);
        return Long.parseLong(http.post(other, "/cases", body, 201).path("case_id").asString());
    }
}
