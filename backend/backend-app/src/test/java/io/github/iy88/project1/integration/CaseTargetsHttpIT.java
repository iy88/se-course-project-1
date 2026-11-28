package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/** Case target projection, disposition and report-scope rules across content, trade and messages. */
class CaseTargetsHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;
    private static Session manager;
    private static Session reporter;
    private static Session seller;
    private static Session buyer;
    private static Session other;
    private static long product;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("case-targets");
        manager = http.account("target-manager", "manager");
        reporter = http.account("target-reporter", "user");
        seller = http.account("target-seller", "user");
        buyer = http.account("target-buyer", "user");
        other = http.account("target-other", "user");
        product = http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 100, 'public') returning product_id
                """).param(http.accountId(seller)).param("Target product " + RUN).query(Long.class).single();
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void commentEvaluationTradeAndMessageTargetsRespectReportScope() throws Exception {
        var comment = http.post(buyer, "/products/" + product + "/comments",
                "{\"body\":\"reportable root\"}", 201);
        long commentId = comment.path("id").asLong();
        var reply = http.post(seller, "/products/" + product + "/comments/" + commentId + "/replies",
                "{\"body\":\"seller reply\"}", 201);
        long replyId = reply.path("id").asLong();
        http.post(buyer, "/cases", """
                {"target":{"target_type":"comment","target_id":"%d"},"reason":"own comment"}
                """.formatted(commentId), 422);
        http.post(seller, "/cases", """
                {"target":{"target_type":"comment","target_id":"%d"},"reason":"comment abuse"}
                """.formatted(commentId), 201);
        http.post(buyer, "/cases", """
                {"target":{"target_type":"comment","target_id":"%d"},"reason":"reply abuse"}
                """.formatted(replyId), 201);
        http.post(seller, "/cases",
                "{\"target\":{\"target_type\":\"comment\",\"target_id\":\"999999999\"},\"reason\":\"gone\"}", 422);

        long trade = completedTradeWithReview();
        long reviewId = http.db.sql("select id from trade_review where trade_id = ? and reviewer_id = ?")
                .param(trade).param(http.accountId(buyer)).query(Long.class).single();
        http.post(buyer, "/cases", """
                {"target":{"target_type":"evaluation","target_id":"%d"},"reason":"own review"}
                """.formatted(reviewId), 422);
        http.post(seller, "/cases", """
                {"target":{"target_type":"evaluation","target_id":"%d"},"reason":"review abuse"}
                """.formatted(reviewId), 201);
        http.post(seller, "/cases",
                "{\"target\":{\"target_type\":\"evaluation\",\"target_id\":\"999999999\"},\"reason\":\"gone\"}", 422);

        long activeTrade = activeTrade();
        http.post(other, "/cases", """
                {"target":{"target_type":"trade","target_id":"%d"},"reason":"outsider"}
                """.formatted(activeTrade), 422);
        http.post(buyer, "/cases", """
                {"target":{"target_type":"trade","target_id":"%d"},"reason":"trade issue"}
                """.formatted(activeTrade), 201);

        var chat = http.post(buyer, "/conversations/private",
                "{\"target_account_id\":\"" + http.accountId(seller) + "\"}", 200);
        long chatId = chat.path("conversation_id").asLong();
        long chatMessage = http.post(buyer, "/conversations/chat/" + chatId + "/messages",
                "{\"body\":\"reportable chat\"}", 201).path("message_id").asLong();
        http.post(buyer, "/cases", """
                {"target":{"target_type":"message","target_id":"%d",
                           "conversation_kind":"chat","conversation_id":"%d"},
                 "reason":"own message"}
                """.formatted(chatMessage, chatId), 422);
        http.post(other, "/cases", """
                {"target":{"target_type":"message","target_id":"%d",
                           "conversation_kind":"chat","conversation_id":"%d"},
                 "reason":"not a participant"}
                """.formatted(chatMessage, chatId), 422);
        http.post(seller, "/cases", """
                {"target":{"target_type":"message","target_id":"%d",
                           "conversation_kind":"chat","conversation_id":"%d"},
                 "reason":"chat abuse"}
                """.formatted(chatMessage, chatId), 201);

        var commentCase = http.post(other, "/cases", """
                {"target":{"target_type":"comment","target_id":"%d"},"reason":"remove content"}
                """.formatted(commentId), 201);
        long contentCase = commentCase.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + contentCase + "/claim", null, 200);
        http.get(manager, "/cases/" + contentCase, 200);
        var removed = http.post(manager, "/admin/cases/" + contentCase + "/decisions", """
                {"decision_kind":"violation","reason":"remove hostile comment","basis_refs":[],
                 "enforcements":[{"action":"remove_content","target_type":"comment",
                                  "target_id":"%d"}]}
                """.formatted(commentId), 201);
        assertThat(removed.at("/enforcements/0/action").asString()).isEqualTo("remove_content");

        var accountCase = http.post(reporter, "/cases", """
                {"target":{"target_type":"account","target_id":"%d","source_product_id":"%d"},
                 "reason":"seller conduct"}
                """.formatted(http.accountId(seller), product), 201);
        long accountCaseId = accountCase.path("case_id").asLong();
        http.post(manager, "/admin/cases/" + accountCaseId + "/claim", null, 200);
        assertThat(http.get(manager, "/cases/" + accountCaseId, 200)
                .path("disposition_targets").path("products").isArray()).isTrue();
    }

    private long completedTradeWithReview() {
        long trade = http.db.sql("""
                insert into trade (product_id, buyer_id, seller_id, status, terminal_reason, requested_at,
                                   responded_at, ended_at, created_at, updated_at)
                values (?, ?, ?, 'completed', 'completed', now(), now(), now(), now(), now()) returning id
                """).param(product).param(http.accountId(buyer)).param(http.accountId(seller))
                .query(Long.class).single();
        http.db.sql("""
                insert into trade_review (trade_id, reviewer_id, reviewee_id, rating, content, visible, created_at)
                values (?, ?, ?, 5, 'reportable review', true, now())
                """).param(trade).param(http.accountId(buyer)).param(http.accountId(seller)).update();
        return trade;
    }

    private long activeTrade() {
        long trade = http.db.sql("""
                insert into trade (product_id, buyer_id, seller_id, status, requested_at, responded_at,
                                   created_at, updated_at)
                values (?, ?, ?, 'in_progress', now(), now(), now(), now()) returning id
                """).param(product).param(http.accountId(buyer)).param(http.accountId(seller))
                .query(Long.class).single();
        http.db.sql("insert into trade_conversation (trade_id, created_at) values (?, now())")
                .param(trade).update();
        return trade;
    }
}
