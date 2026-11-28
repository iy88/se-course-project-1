package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/**
 * Case lifecycle and subject enforcement through the HTTP API. Reports, claims, inquiries,
 * decisions, explicit lifts, publication and personal result lists all run on the production
 * application services against the isolated PostgreSQL/Redis fixture.
 */
class CaseModerationHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;
    private static Session manager;
    private static Session manager2;
    private static Session reporter;
    private static Session seller;
    private static Session other;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("case-moderation");
        manager = http.account("case-manager", "manager");
        manager2 = http.account("case-manager2", "manager");
        reporter = http.account("case-reporter", "user");
        seller = http.account("case-seller", "user");
        other = http.account("case-other", "user");
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void reportListDetailSupplementInquiryDecisionCloseAndPublicResult() throws Exception {
        long product = publicProduct("Case target " + RUN);
        var report = http.post(reporter, "/cases", """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"misleading content"}
                """.formatted(product), 201);
        long caseId = report.path("case_id").asLong();
        http.get(reporter, "/cases?scope=mine&page=1&page_size=10", 200);
        http.get(reporter, "/cases?scope=received&page=1&page_size=10", 200);
        http.get(reporter, "/cases?scope=bad", 422);
        http.get(reporter, "/cases?scope=mine&status=bad", 422);
        http.get(reporter, "/cases?scope=mine&page=0", 422);
        http.get(reporter, "/cases?scope=mine&page_size=1000", 422);
        http.get(other, "/cases/" + caseId, 404);
        http.get(manager, "/cases/" + caseId, 404);
        http.get(reporter, "/cases/" + caseId, 200);
        http.post(other, "/cases/" + caseId + "/supplements",
                "{\"note\":\"not my case\"}", 404);
        var supplement = http.post(reporter, "/cases/" + caseId + "/supplements",
                "{\"note\":\"more context\"}", 200);
        assertThat(supplement.path("case_id").asString()).isEqualTo(Long.toString(caseId));

        var claim = http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        assertThat(claim.path("case_id").asLong()).isEqualTo(caseId);
        http.post(manager2, "/admin/cases/" + caseId + "/claim", null, 409);
        http.post(reporter, "/admin/cases/" + caseId + "/inquiries", "{}", 422);
        var inquiry = http.post(manager, "/admin/cases/" + caseId + "/inquiries",
                "{\"peer_account_id\":\"" + http.accountId(seller) + "\",\"scope_text\":\"explain the listing\"}",
                201);
        long conversation = inquiry.at("/thread/conversation_id").asLong();
        long inquiryId = inquiry.path("inquiry_action_id").asLong();
        var statement = http.post(seller, "/cases/" + caseId + "/messages", """
                {"thread":{"conversation_kind":"case","conversation_id":"%d"},
                 "message_kind":"statement","body":"it is accurate",
                 "inquiry_action_id":"%d"}
                """.formatted(conversation, inquiryId), 201);
        assertThat(statement.at("/thread/conversation_id").asLong()).isEqualTo(conversation);
        http.get(manager, "/cases/" + caseId, 200);
        http.get(manager, "/admin/cases/" + caseId + "/evidence/999999999", 404);

        var decision = http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"violation","reason":"confirmed misleading","basis_refs":[],
                 "enforcements":[{"action":"withdraw_public_access","target_type":"product",
                                  "target_id":"%d"}]}
                """.formatted(product), 201);
        String enforcement = decision.at("/enforcements/0/enforcement_id").asString();
        assertThat(decision.at("/enforcements/0/action").asString()).isEqualTo("withdraw_public_access");
        http.get(other, "/products/" + product, 404);
        var lifted = http.post(manager, "/admin/cases/" + caseId + "/enforcements/" + enforcement + "/lift",
                "{\"reason\":\"evidence reviewed\"}", 200);
        assertThat(lifted.path("remaining_restrictions").isArray()).isTrue();
        assertThat(http.get(other, "/products/" + product, 200).path("lifecycle_state").asString())
                .isEqualTo("public");
        http.post(manager2, "/admin/cases/" + caseId + "/enforcements/" + enforcement + "/lift",
                "{\"reason\":\"not the claimant\"}", 404);

        http.post(manager, "/admin/cases/" + caseId + "/close", null, 200);
        var published = http.post(manager, "/admin/cases/" + caseId + "/publish-result",
                "{\"public_summary\":\"content reviewed\",\"public_reason\":\"policy\"}", 200);
        assertThat(published.path("public_result_at").isNull()).isFalse();
        var results = http.get(reporter, "/case-results?target_type=product&target_id=" + product
                + "&page=1&page_size=10", 200);
        assertThat(results.path("total").asLong()).isGreaterThanOrEqualTo(1);
        http.get(reporter, "/case-results?page=0", 422);
        http.get(reporter, "/case-results?target_type=product&target_id=bad", 422);
        http.get(reporter, "/case-results?conversation_kind=chat&conversation_id=bad", 422);
        http.get(reporter, "/cases?scope=mine&archived=true&page=1&page_size=10", 200);
        http.get(manager, "/management/todos?page=0", 422);
        http.get(manager, "/management/todos?ownership=bad", 422);
        http.get(manager, "/management/todos?kind=bad", 422);
        http.get(reporter, "/management/todos", 403);
    }

    @Test
    void accountRestrictionAndProductWithdrawalAreLiftedThroughExplicitCaseEnforcement() throws Exception {
        long product = publicProduct("Restricted product " + RUN);
        var accountReport = http.post(reporter, "/cases", """
                {"target":{"target_type":"account","target_id":"%d"},"reason":"abusive behaviour"}
                """.formatted(http.accountId(seller)), 201);
        long accountCase = accountReport.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + accountCase + "/claim", null, 200);
        var accountDecision = http.post(manager, "/admin/cases/" + accountCase + "/decisions", """
                {"decision_kind":"violation","reason":"confirmed abuse","basis_refs":[],
                 "enforcements":[{"action":"restrict_account","target_type":"account",
                                  "target_id":"%d"}]}
                """.formatted(http.accountId(seller)), 201);
        String accountEnforcement = accountDecision.at("/enforcements/0/enforcement_id").asString();
        assertThat(http.get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean())
                .isTrue();
        assertThat(http.get(other, "/products/" + product, 404).path("error").path("code").asString())
                .isEqualTo("RESOURCE_NOT_VISIBLE");
        var accountThread = http.get(seller, "/cases/" + accountCase, 200).path("thread");
        var appealBody = http.json.createObjectNode().put("message_kind", "appeal")
                .put("body", "please review the restriction");
        appealBody.set("thread", accountThread);
        var appeal = http.post(seller, "/cases/" + accountCase + "/messages", appealBody.toString(), 201);
        String appealId = appeal.path("case_action_id").asString();
        var replyBody = http.json.createObjectNode().put("message_kind", "manager_reply")
                .put("body", "appeal accepted").put("appeal_action_id", appealId)
                .put("resolution", "revoke").put("basis_ref", "case:" + accountCase)
                .put("original_enforcement_id", accountEnforcement);
        replyBody.set("thread", accountThread);
        http.post(manager, "/cases/" + accountCase + "/messages", replyBody.toString(), 201);
        assertThat(http.get(seller, "/account/session", 200).at("/account/write_restricted").asBoolean())
                .isFalse();
        assertThat(http.get(other, "/products/" + product, 200).path("lifecycle_state").asString())
                .isEqualTo("public");

        var productReport = http.post(reporter, "/cases", """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"withdraw this listing"}
                """.formatted(product), 201);
        long productCase = productReport.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + productCase + "/claim", null, 200);
        var productDecision = http.post(manager, "/admin/cases/" + productCase + "/decisions", """
                {"decision_kind":"violation","reason":"listing withdrawn","basis_refs":[],
                 "enforcements":[{"action":"withdraw_public_access","target_type":"product",
                                  "target_id":"%d"}]}
                """.formatted(product), 201);
        String productEnforcement = productDecision.at("/enforcements/0/enforcement_id").asString();
        http.get(other, "/products/" + product, 404);
        http.post(manager, "/admin/cases/" + productCase + "/enforcements/" + productEnforcement + "/lift",
                "{\"reason\":\"listing corrected\"}", 200);
        assertThat(http.get(other, "/products/" + product, 200).path("lifecycle_state").asString())
                .isEqualTo("public");
        http.post(manager, "/admin/cases/" + productCase + "/enforcements/999999999/lift",
                "{\"reason\":\"unknown\"}", 404);
    }

    @Test
    void caseValidationMessagesEvidenceAndNotificationsStayScoped() throws Exception {
        long product = publicProduct("Notification product " + RUN);
        http.post(seller, "/cases", """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"own product"}
                """.formatted(product), 422);
        http.post(reporter, "/cases", "{}", 422);
        http.post(reporter, "/cases",
                "{\"target\":{\"target_type\":\"product\"},\"reason\":\"missing id\"}", 422);
        http.post(reporter, "/cases",
                "{\"target\":{\"target_type\":\"product\",\"target_id\":\"bad\"},\"reason\":\"bad id\"}",
                422);
        http.post(reporter, "/cases",
                "{\"target\":{\"target_type\":\"bad\",\"target_id\":\"1\"},\"reason\":\"bad type\"}",
                422);
        http.post(reporter, "/cases",
                "{\"target\":{\"target_type\":\"product\",\"target_id\":\"999999999\"},\"reason\":\"gone\"}",
                422);
        http.get(reporter, "/cases/not-a-number", 404);
        http.post(reporter, "/cases/not-a-number/supplements", "{\"note\":\"x\"}", 404);
        http.post(manager, "/admin/cases/not-a-number/claim", null, 404);

        var report = http.post(reporter, "/cases", """
                {"target":{"target_type":"product","target_id":"%d"},"reason":"notification flow"}
                """.formatted(product), 201);
        long caseId = report.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        var inquiry = http.post(manager, "/admin/cases/" + caseId + "/inquiries",
                "{\"peer_account_id\":\"" + http.accountId(seller) + "\",\"scope_text\":\"please explain\"}",
                201);
        long conversation = inquiry.at("/thread/conversation_id").asLong();
        long inquiryMessage = inquiry.path("case_message_id").asLong();
        var sellerNotices = http.get(seller, "/account/notifications?event_type=case.inquiry_created", 200);
        assertThat(sellerNotices.path("total").asLong()).isGreaterThanOrEqualTo(1);
        long sellerNotice = sellerNotices.at("/items/0/notification_id").asLong();
        assertThat(http.get(seller, "/account/notifications/" + sellerNotice, 200)
                .path("source").path("resource_type").asString()).isEqualTo("case");
        assertThat(http.get(manager, "/account/notifications?audience=management&page=1&page_size=20", 200)
                .path("items").isArray()).isTrue();

        var statement = http.post(seller, "/cases/" + caseId + "/messages", """
                {"thread":{"conversation_kind":"case","conversation_id":"%d"},
                 "message_kind":"statement","body":"seller statement",
                 "inquiry_action_id":"%d"}
                """.formatted(conversation, inquiry.path("inquiry_action_id").asLong()), 201);
        assertThat(statement.path("case_message_id").asLong()).isPositive();

        http.post(manager, "/admin/cases/" + caseId + "/evidence", """
                {"conversation_kind":"case","conversation_id":"%d","message_id":"999999999"}
                """.formatted(conversation), 422);
        http.post(manager, "/admin/cases/" + caseId + "/evidence", """
                {"conversation_kind":"bad","conversation_id":"%d","message_id":"%d"}
                """.formatted(conversation, inquiryMessage), 422);

        var decided = http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"violation","reason":"confirmed","basis_refs":[],
                 "enforcements":[{"action":"withdraw_public_access","target_type":"product",
                                  "target_id":"999999999"}]}
                """, 409);
        assertThat(decided.path("error").path("code").asString()).isEqualTo("PRODUCT_NOT_AVAILABLE");
        http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"violation","reason":"confirmed","basis_refs":[],
                 "enforcements":[{"action":"withdraw_public_access","target_type":"account",
                                  "target_id":"%d"}]}
                """.formatted(http.accountId(seller)), 422);

        http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"no_action","reason":"no enforcement needed","basis_refs":[],
                 "enforcements":[]}
                """, 201);
        var closed = http.post(manager, "/admin/cases/" + caseId + "/close", null, 200);
        assertThat(closed.path("archived_at").isNull()).isFalse();
        http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"no_action","reason":"late","basis_refs":[],"enforcements":[]}
                """, 409);

        var chat = http.post(other, "/conversations/private",
                "{\"target_account_id\":\"" + http.accountId(seller) + "\"}", 200);
        long chatId = chat.path("conversation_id").asLong();
        var chatMessage = http.post(other, "/conversations/chat/" + chatId + "/messages",
                "{\"body\":\"reported message\"}", 201);
        long messageId = chatMessage.path("message_id").asLong();
        var messageCase = http.post(seller, "/cases", """
                {"target":{"target_type":"message","target_id":"%d",
                           "conversation_kind":"chat","conversation_id":"%d"},
                 "reason":"reported chat message"}
                """.formatted(messageId, chatId), 201);
        long reportedCase = messageCase.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + reportedCase + "/claim", null, 200);
        var evidence = http.post(manager, "/admin/cases/" + reportedCase + "/evidence", """
                {"conversation_kind":"chat","conversation_id":"%d","message_id":"%d"}
                """.formatted(chatId, messageId), 201);
        assertThat(evidence.at("/source_ref/resource_id").asString()).isEqualTo(Long.toString(messageId));
        http.get(manager, "/admin/cases/" + reportedCase + "/evidence/"
                + evidence.path("evidence_id").asString(), 200);
        http.get(manager2, "/admin/cases/" + reportedCase + "/evidence/"
                + evidence.path("evidence_id").asString(), 404);
    }

    private long publicProduct(String title) {
        return http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 1000, 'public') returning product_id
                """).param(http.accountId(seller)).param(title).query(Long.class).single();
    }
}
