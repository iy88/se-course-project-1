package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.integration.HttpItSupport.Session;
import io.github.iy88.project1.trade.application.TradeApplication;
import io.github.iy88.project1.trade.application.TradeCommands;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/**
 * End-to-end trade and conversation workflows through the public HTTP API. Products are inserted
 * directly because their lifecycle is covered by {@link CategoryProductHttpIT}; every trade, chat,
 * case-thread and notification transition below goes through the production application services.
 */
class TradeConversationHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;
    private static Session seller;
    private static Session buyer;
    private static Session other;
    private static Session manager;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("trade-conversation");
        seller = http.account("trade-seller", "user");
        buyer = http.account("trade-buyer", "user");
        other = http.account("trade-other", "user");
        manager = http.account("trade-manager", "manager");
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void agreementCompletionReviewsAndNotificationsFlowThroughHttp() throws Exception {
        long product = publicProduct("Completed " + RUN);
        int productVersion = http.get(seller, "/products/" + product, 200).path("content_version").asInt();
        var requested = http.post(buyer, "/products/" + product + "/purchase-requests",
                "{\"note\":\"please sell\",\"expected_product_version\":" + productVersion + "}", 201);
        long trade = requested.path("id").asLong();
        assertThat(requested.path("status").asString()).isEqualTo("pending_acceptance");
        assertThat(http.get(seller, "/account/todos?kind=request_response&page=1&page_size=10", 200)
                .path("total").asLong()).isGreaterThanOrEqualTo(1);
        http.post(buyer, "/products/" + product + "/purchase-requests",
                "{\"note\":\"again\",\"expected_product_version\":" + productVersion + "}", 409);
        http.post(seller, "/trades/" + trade + "/accept",
                "{\"expected_version\":" + requested.path("version").asInt() + "}", 200);

        var mine = http.get(seller, "/me/trades?role=seller&status=in_progress&page=1&page_size=10", 200);
        assertThat(mine.path("total").asLong()).isGreaterThanOrEqualTo(1);
        http.get(seller, "/me/trades?role=bad", 422);
        http.get(seller, "/me/trades?status=bad", 422);
        http.get(seller, "/me/trades?page=0", 422);
        http.get(seller, "/me/trades?page_size=101", 422);
        http.get(other, "/trades/" + trade, 404);

        int proposalVersion = tradeVersion(seller, trade);
        var proposal = http.post(seller, "/trades/" + trade + "/agreements", """
                {"delivery_at":"2026-12-01T10:00:00Z","delivery_place_text":"fixture place",
                 "delivery_method":"face_to_face","amount_cents":1200,"payment_method":"offline",
                 "payment_timing":"on_delivery","expected_version":%d}
                """.formatted(proposalVersion), 201);
        long agreement = proposal.at("/agreement/id").asLong();
        assertThat(http.get(buyer, "/account/todos?kind=agreement_response&page=1&page_size=10", 200)
                .path("total").asLong()).isGreaterThanOrEqualTo(1);
        int decideVersion = tradeVersion(buyer, trade);
        http.post(buyer, "/trades/" + trade + "/agreements/" + agreement + "/decisions",
                "{\"decision\":\"accept\",\"expected_version\":" + decideVersion + "}", 200);
        var detail = http.get(buyer, "/trades/" + trade
                + "?include=agreement_history,confirmation_history,state_history", 200);
        assertThat(detail.at("/agreement/current/id").asString()).isEqualTo(Long.toString(agreement));
        http.get(buyer, "/trades/" + trade + "?include=bad", 422);

        int version = tradeVersion(seller, trade);
        http.post(seller, "/trades/" + trade + "/completion-confirmations",
                "{\"note\":\"handed over\",\"expected_version\":" + version + "}", 201);
        assertThat(http.get(buyer, "/account/todos?kind=completion_response&page=1&page_size=10", 200)
                .path("total").asLong()).isGreaterThanOrEqualTo(1);
        version = tradeVersion(buyer, trade);
        var completed = http.post(buyer, "/trades/" + trade + "/completion-confirmations",
                "{\"note\":\"received\",\"expected_version\":" + version + "}", 201);
        assertThat(completed.at("/trade/status").asString()).isEqualTo("completed");

        var review = http.post(seller, "/trades/" + trade + "/reviews",
                "{\"rating\":5,\"content\":\"smooth deal\"}", 201);
        assertThat(review.at("/review/rating").asInt()).isEqualTo(5);
        http.post(seller, "/trades/" + trade + "/reviews",
                "{\"rating\":4,\"content\":\"again\"}", 409);
        http.post(buyer, "/trades/" + trade + "/reviews",
                "{\"rating\":\"five\",\"content\":\"bad rating\"}", 422);
        http.post(buyer, "/trades/" + trade + "/reviews",
                "{\"rating\":4,\"content\":\"\"}", 422);
        http.post(buyer, "/trades/" + trade + "/reviews",
                "{\"rating\":4,\"content\":\"thanks\"}", 201);
        var reviews = http.get(buyer, "/trades/" + trade + "/reviews", 200);
        assertThat(reviews.path("can_review").asBoolean()).isFalse();
        assertThat(reviews.path("written").isNull()).isFalse();
        assertThat(reviews.path("received").isNull()).isFalse();
        http.get(other, "/trades/" + trade + "/reviews", 404);
        http.get(seller, "/me/reviews?direction=written", 200);
        http.get(seller, "/me/reviews?direction=received&page=1&page_size=5", 200);
        http.get(seller, "/me/reviews?direction=bad", 422);
        http.get(seller, "/me/reviews?page=0", 422);
        http.get(seller, "/account/resources?kind=trade&role=selling&state=completed", 200);
        http.get(seller, "/account/resources?kind=evaluation&direction=written", 200);
        http.get(seller, "/account/resources?kind=evaluation&direction=received", 200);
        assertThat(http.get(seller, "/account/overview", 200).at("/evaluations/written").asLong())
                .isGreaterThanOrEqualTo(1);

        var notifications = http.get(seller, "/account/notifications?read=unread&page=1&page_size=20", 200);
        assertThat(notifications.path("total").asLong()).isGreaterThanOrEqualTo(1);
        long notificationId = notifications.at("/items/0/notification_id").asLong();
        http.get(seller, "/account/notifications/" + notificationId, 200);
        http.get(other, "/account/notifications/" + notificationId, 404);
        http.get(seller, "/account/notifications?read=bad", 422);
        http.get(seller, "/account/notifications?page=0", 422);
        http.get(seller, "/account/notifications?page_size=101", 422);
        http.get(seller, "/account/notifications?audience=bad", 422);
        http.get(seller, "/account/notifications?audience=management", 403);
        http.get(manager, "/account/notifications?audience=management", 200);
        var read = http.put(seller, "/account/notifications/" + notificationId + "/read", null, 200);
        assertThat(read.path("notification_id").asLong()).isEqualTo(notificationId);
        http.get(seller, "/account/notifications?read=read", 200);
    }

    @Test
    void rejectionWithdrawalCancellationAndDisputeKeepTheTradeStateConsistent() throws Exception {
        long rejectedProduct = publicProduct("Rejected " + RUN);
        var rejectedRequest = purchase(rejectedProduct);
        long rejectedTrade = rejectedRequest.path("id").asLong();
        http.post(buyer, "/trades/" + rejectedTrade + "/accept",
                "{\"expected_version\":" + rejectedRequest.path("version").asInt() + "}", 403);
        var rejected = http.post(seller, "/trades/" + rejectedTrade + "/reject",
                "{\"reason\":\"not for sale\",\"expected_version\":" + rejectedRequest.path("version").asInt() + "}",
                200);
        assertThat(rejected.path("status").asString()).isEqualTo("rejected");
        http.post(buyer, "/trades/" + rejectedTrade + "/withdraw",
                "{\"expected_version\":" + rejected.path("version").asInt() + "}", 409);

        long withdrawnProduct = publicProduct("Withdrawn " + RUN);
        var withdrawnRequest = purchase(withdrawnProduct);
        long withdrawnTrade = withdrawnRequest.path("id").asLong();
        var withdrawn = http.post(buyer, "/trades/" + withdrawnTrade + "/withdraw",
                "{\"expected_version\":" + withdrawnRequest.path("version").asInt() + "}", 200);
        assertThat(withdrawn.path("status").asString()).isEqualTo("withdrawn");
        http.post(seller, "/trades/" + withdrawnTrade + "/accept",
                "{\"expected_version\":" + withdrawn.path("version").asInt() + "}", 409);

        long cancelledProduct = publicProduct("Cancelled " + RUN);
        var cancelledRequest = purchase(cancelledProduct);
        long cancelledTrade = cancelledRequest.path("id").asLong();
        http.post(seller, "/trades/" + cancelledTrade + "/accept",
                "{\"expected_version\":" + cancelledRequest.path("version").asInt() + "}", 200);
        effectiveAgreement(cancelledTrade);

        int version = tradeVersion(buyer, cancelledTrade);
        var proposal = http.post(buyer, "/trades/" + cancelledTrade + "/cancellation-proposals",
                "{\"reason\":\"change of mind\",\"expected_version\":" + version + "}", 201);
        assertThat(proposal.path("mode").asString()).isEqualTo("approval");
        long proposalId = proposal.at("/proposal/id").asLong();
        version = tradeVersion(seller, cancelledTrade);
        var rejectedCancellation = http.post(seller,
                "/trades/" + cancelledTrade + "/cancellation-proposals/" + proposalId + "/decisions",
                "{\"decision\":\"reject\",\"expected_version\":" + version + "}", 200);
        assertThat(rejectedCancellation.at("/proposal/status").asString()).isEqualTo("rejected");

        version = tradeVersion(seller, cancelledTrade);
        var sellerProposal = http.post(seller, "/trades/" + cancelledTrade + "/cancellation-proposals",
                "{\"reason\":\"seller withdraws\",\"expected_version\":" + version + "}", 201);
        long sellerProposalId = sellerProposal.at("/proposal/id").asLong();
        version = tradeVersion(seller, cancelledTrade);
        http.post(seller, "/trades/" + cancelledTrade + "/cancellation-proposals/" + sellerProposalId
                        + "/decisions",
                "{\"decision\":\"withdraw\",\"expected_version\":" + version + "}", 200);

        version = tradeVersion(buyer, cancelledTrade);
        var secondProposal = http.post(buyer, "/trades/" + cancelledTrade + "/cancellation-proposals",
                "{\"reason\":\"confirm cancel\",\"expected_version\":" + version + "}", 201);
        long secondProposalId = secondProposal.at("/proposal/id").asLong();
        version = tradeVersion(seller, cancelledTrade);
        var terminated = http.post(seller, "/trades/" + cancelledTrade + "/cancellation-proposals/"
                        + secondProposalId + "/decisions",
                "{\"decision\":\"accept\",\"expected_version\":" + version + "}", 200);
        assertThat(terminated.at("/trade/status").asString()).isEqualTo("terminated");
        assertThat(http.get(buyer, "/products/" + cancelledProduct, 200).path("lifecycle_state").asString())
                .isEqualTo("public");

        long disputedProduct = publicProduct("Disputed " + RUN);
        var disputedRequest = purchase(disputedProduct);
        long disputedTrade = disputedRequest.path("id").asLong();
        http.post(seller, "/trades/" + disputedTrade + "/accept",
                "{\"expected_version\":" + disputedRequest.path("version").asInt() + "}", 200);
        effectiveAgreement(disputedTrade);
        version = tradeVersion(buyer, disputedTrade);
        var dispute = http.post(buyer, "/trades/" + disputedTrade + "/disputes",
                "{\"statement\":\"delivery differs\",\"expected_version\":" + version + "}", 201);
        long disputeId = dispute.at("/dispute/id").asLong();
        assertThat(dispute.at("/trade/status").asString()).isEqualTo("disputed");
        version = tradeVersion(seller, disputedTrade);
        var first = http.post(seller,
                "/trades/" + disputedTrade + "/disputes/" + disputeId + "/resolution-confirmations",
                "{\"expected_version\":" + version + "}", 200);
        assertThat(first.at("/trade/status").asString()).isEqualTo("disputed");
        version = tradeVersion(buyer, disputedTrade);
        var resolved = http.post(buyer,
                "/trades/" + disputedTrade + "/disputes/" + disputeId + "/resolution-confirmations",
                "{\"expected_version\":" + version + "}", 200);
        assertThat(resolved.at("/trade/status").asString()).isEqualTo("in_progress");
        http.post(buyer,
                "/trades/" + disputedTrade + "/disputes/" + disputeId + "/resolution-confirmations",
                "{\"expected_version\":" + resolved.at("/trade/version").asInt() + "}", 409);
    }

    @Test
    void privateTradeAndCaseConversationsSharePagingAccessAndReadProgress() throws Exception {
        long product = publicProduct("Conversation " + RUN);
        var requested = purchase(product);
        long trade = requested.path("id").asLong();
        var accepted = http.post(seller, "/trades/" + trade + "/accept",
                "{\"expected_version\":" + requested.path("version").asInt() + "}", 200);
        long tradeConversation = accepted.path("trade_conversation_id").asLong();

        var started = http.post(buyer, "/conversations/private",
                "{\"target_account_id\":\"" + http.accountId(seller) + "\"}", 200);
        long chat = started.path("conversation_id").asLong();
        assertThat(started.path("conversation_kind").asString()).isEqualTo("chat");
        assertThat(started.path("reused").asBoolean()).isFalse();
        assertThat(http.post(buyer, "/conversations/private",
                "{\"target_account_id\":\"" + http.accountId(seller) + "\"}", 200)
                .path("reused").asBoolean()).isTrue();
        http.post(buyer, "/conversations/private",
                "{\"target_account_id\":\"" + http.accountId(buyer) + "\"}", 422);
        http.post(buyer, "/conversations/private", "{}", 422);
        http.post(buyer, "/conversations/private",
                "{\"target_account_id\":\"999999999\"}", 404);

        var sent = http.post(buyer, "/conversations/chat/" + chat + "/messages",
                "{\"body\":\"hello seller\"}", 201);
        long sequence = sent.path("seq").asLong();
        assertThat(sent.path("unread_count").asLong()).isEqualTo(1);
        http.post(buyer, "/conversations/chat/" + chat + "/messages", "{\"body\":\" \"}", 422);
        http.post(other, "/conversations/chat/" + chat + "/messages", "{\"body\":\"intrude\"}", 404);
        http.get(other, "/conversations/chat/" + chat + "/messages", 404);
        http.get(buyer, "/conversations/chat/" + chat + "/messages?limit=1", 200);
        http.get(buyer, "/conversations/chat/" + chat + "/messages?after_seq=0", 200);
        http.get(buyer, "/conversations/chat/" + chat + "/messages?before_seq=99", 200);
        http.get(buyer, "/conversations/chat/" + chat + "/messages?before_seq=1&after_seq=0", 422);
        http.get(buyer, "/conversations/chat/" + chat + "/messages?limit=0", 422);
        http.get(buyer, "/conversations/chat/" + chat + "/messages?limit=101", 422);
        http.get(buyer, "/conversations/bogus/" + chat + "/messages", 422);
        http.get(buyer, "/conversations/chat/not-a-number/messages", 404);

        var progress = http.post(seller, "/conversations/chat/" + chat + "/read-progress",
                "{\"displayed_seq\":" + sequence + "}", 200);
        assertThat(progress.path("unread_count").asLong()).isZero();
        http.post(seller, "/conversations/chat/" + chat + "/read-progress",
                "{\"displayed_seq\":-1}", 422);
        http.post(other, "/conversations/chat/" + chat + "/read-progress",
                "{\"displayed_seq\":0}", 404);
        http.post(seller, "/conversations/case/" + chat + "/messages",
                "{\"body\":\"not here\"}", 403);

        var list = http.get(buyer, "/conversations?page=1&page_size=20", 200);
        assertThat(list.path("total").asLong()).isGreaterThanOrEqualTo(1);
        http.get(buyer, "/conversations?page=0", 422);
        http.get(buyer, "/conversations?page_size=0", 422);
        http.get(buyer, "/conversations?page=999&page_size=20", 200);

        var tradeMessage = http.post(buyer, "/conversations/trade/" + tradeConversation + "/messages",
                "{\"body\":\"trade question\"}", 201);
        http.post(other, "/conversations/trade/" + tradeConversation + "/messages",
                "{\"body\":\"no access\"}", 404);
        http.get(other, "/conversations/trade/" + tradeConversation + "/messages", 404);
        http.get(seller, "/conversations/trade/" + tradeConversation + "/messages?limit=10", 200);
        http.get(seller, "/conversations/trade/" + tradeConversation + "/messages?before_seq=1&after_seq=0", 422);
        http.post(seller, "/conversations/trade/" + tradeConversation + "/read-progress",
                "{\"displayed_seq\":" + tradeMessage.path("seq").asLong() + "}", 200);

        long caseId = Long.parseLong(http.post(buyer, "/cases", """
                {"target":{"target_type":"trade","target_id":"%d"},"reason":"check the conversation"}
                """.formatted(trade), 201).path("case_id").asString());
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        var inquiry = http.post(manager, "/admin/cases/" + caseId + "/inquiries",
                "{\"peer_account_id\":\"" + http.accountId(seller) + "\",\"scope_text\":\"please explain\"}", 201);
        long caseConversation = inquiry.at("/thread/conversation_id").asLong();
        var casePage = http.get(seller, "/conversations/case/" + caseConversation + "/messages?limit=10", 200);
        assertThat(casePage.path("items").size()).isGreaterThanOrEqualTo(1);
        http.get(other, "/conversations/case/" + caseConversation + "/messages", 404);
        http.get(buyer, "/conversations/case/" + caseConversation + "/messages", 404);
        http.get(seller, "/conversations/case/" + caseConversation + "/messages?before_seq=1&after_seq=0", 422);
        long lastSeq = casePage.path("items").get(casePage.path("items").size() - 1).path("seq").asLong();
        http.post(seller, "/conversations/case/" + caseConversation + "/read-progress",
                "{\"displayed_seq\":" + lastSeq + "}", 200);
        http.post(other, "/conversations/case/" + caseConversation + "/read-progress",
                "{\"displayed_seq\":0}", 404);
    }

    @Test
    void agreementDecisionsAndAdminTradeResolutionCoverEdgeBranches() throws Exception {
        long product = publicProduct("Agreement " + RUN);
        var requested = purchase(product);
        long trade = requested.path("id").asLong();
        http.post(seller, "/trades/" + trade + "/accept",
                "{\"expected_version\":" + requested.path("version").asInt() + "}", 200);

        int version = tradeVersion(seller, trade);
        http.post(seller, "/trades/" + trade + "/agreements",
                "{\"delivery_method\":\"face_to_face\",\"amount_cents\":100,"
                        + "\"expected_version\":" + version + "}", 422);
        http.post(seller, "/trades/" + trade + "/agreements",
                "{\"delivery_at\":\"2026-12-01T10:00:00Z\",\"delivery_place_text\":\"x\","
                        + "\"delivery_method\":\"face_to_face\",\"amount_cents\":-1,"
                        + "\"payment_method\":\"offline\",\"payment_timing\":\"on_delivery\","
                        + "\"expected_version\":" + version + "}", 422);
        var first = http.post(seller, "/trades/" + trade + "/agreements", """
                {"delivery_at":"2026-12-01T10:00:00Z","delivery_place_text":"place",
                 "delivery_method":"face_to_face","amount_cents":100,"payment_method":"offline",
                 "payment_timing":"on_delivery","expected_version":%d}
                """.formatted(version), 201);
        long agreement = first.at("/agreement/id").asLong();
        version = tradeVersion(seller, trade);
        http.post(seller, "/trades/" + trade + "/agreements/" + agreement + "/decisions",
                "{\"decision\":\"accept\",\"expected_version\":" + version + "}", 403);
        http.post(buyer, "/trades/" + trade + "/agreements/" + agreement + "/decisions",
                "{\"decision\":\"bogus\",\"expected_version\":" + version + "}", 422);
        var rejected = http.post(buyer, "/trades/" + trade + "/agreements/" + agreement + "/decisions",
                "{\"decision\":\"reject\",\"expected_version\":" + version + "}", 200);
        assertThat(rejected.at("/trade/agreement/current").isNull()).isTrue();

        version = tradeVersion(seller, trade);
        var second = http.post(seller, "/trades/" + trade + "/agreements", """
                {"delivery_at":"2026-12-02T10:00:00Z","delivery_place_text":"place",
                 "delivery_method":"face_to_face","amount_cents":100,"payment_method":"offline",
                 "payment_timing":"on_delivery","expected_version":%d}
                """.formatted(version), 201);
        long secondAgreement = second.at("/agreement/id").asLong();
        version = tradeVersion(seller, trade);
        http.post(seller, "/trades/" + trade + "/agreements/" + secondAgreement + "/decisions",
                "{\"decision\":\"withdraw\",\"expected_version\":" + version + "}", 200);

        long disputedProduct = publicProduct("Admin dispute " + RUN);
        var disputedRequest = purchase(disputedProduct);
        long disputedTrade = disputedRequest.path("id").asLong();
        http.post(seller, "/trades/" + disputedTrade + "/accept",
                "{\"expected_version\":" + disputedRequest.path("version").asInt() + "}", 200);
        int disputeVersion = tradeVersion(buyer, disputedTrade);
        var dispute = http.post(buyer, "/trades/" + disputedTrade + "/disputes",
                "{\"statement\":\"admin needed\",\"expected_version\":" + disputeVersion + "}", 201);
        long disputeId = dispute.at("/dispute/id").asLong();
        long caseId = dispute.at("/dispute/case_id").asLong();
        http.post(manager, "/admin/cases/" + caseId + "/claim", null, 200);
        var freeze = http.post(manager, "/admin/cases/" + caseId + "/decisions", """
                {"decision_kind":"violation","reason":"freeze pending resolution","basis_refs":[],
                 "enforcements":[{"action":"freeze_trade","target_type":"trade","target_id":"%d"}]}
                """.formatted(disputedTrade), 201);
        String freezeEnforcement = freeze.at("/enforcements/0/enforcement_id").asString();
        var managerIdentity = http.app.getBean(SessionService.class).authenticate(manager.token());
        var context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(http.accountId(manager)), managerIdentity.guard().id(), null,
                (long) managerIdentity.guard().credentialVersion(), "trade-admin-it");
        var resolved = http.app.getBean(TradeApplication.class).resolveDisputeAsAdmin(context, http.key(),
                new TradeCommands.ResolveDispute(caseId, disputeId, "case:" + caseId, "admin resolved"));
        assertThat(resolved.status()).isEqualTo(200);
        assertThat(resolved.data().path("status").asString()).isEqualTo("in_progress");
        http.post(manager, "/admin/cases/" + caseId + "/enforcements/" + freezeEnforcement + "/lift",
                "{\"reason\":\"resolution complete\"}", 200);

        long adjustableProduct = publicProduct("Admin adjust " + RUN);
        var adjustableRequest = purchase(adjustableProduct);
        long adjustableTrade = adjustableRequest.path("id").asLong();
        http.post(seller, "/trades/" + adjustableTrade + "/accept",
                "{\"expected_version\":" + adjustableRequest.path("version").asInt() + "}", 200);
        long adjustableCase = Long.parseLong(http.post(buyer, "/cases", """
                {"target":{"target_type":"trade","target_id":"%d"},"reason":"admin status"}
                """.formatted(adjustableTrade), 201).path("case_id").asString());
        http.post(manager, "/admin/cases/" + adjustableCase + "/claim", null, 200);
        http.post(manager, "/admin/cases/" + adjustableCase + "/decisions", """
                {"decision_kind":"no_action","reason":"no action needed","basis_refs":[],"enforcements":[]}
                """, 201);
        var trades = http.app.getBean(TradeApplication.class);
        assertThatThrownBy(() -> trades.adjustStatus(context, http.key(),
                new TradeCommands.AdjustStatus(adjustableCase, adjustableTrade, "bogus", null, "reason")))
                .isInstanceOf(BusinessError.class);
        var adjusted = trades.adjustStatus(context, http.key(),
                new TradeCommands.AdjustStatus(adjustableCase, adjustableTrade, "terminated",
                        "case:" + adjustableCase, "admin ended"));
        assertThat(adjusted.data().path("status").asString()).isEqualTo("terminated");
        assertThat(http.get(seller, "/products/" + adjustableProduct, 200).path("lifecycle_state").asString())
                .isEqualTo("off_shelf");
    }

    private JsonNode purchase(long product) throws Exception {
        int expectedVersion = http.get(seller, "/products/" + product, 200).path("content_version").asInt();
        return http.post(buyer, "/products/" + product + "/purchase-requests",
                "{\"note\":\"buy " + RUN + "\",\"expected_product_version\":" + expectedVersion + "}", 201);
    }

    private long effectiveAgreement(long trade) throws Exception {
        int version = tradeVersion(seller, trade);
        var proposed = http.post(seller, "/trades/" + trade + "/agreements", """
                {"delivery_at":"2026-12-01T10:00:00Z","delivery_place_text":"fixture place",
                 "delivery_method":"face_to_face","amount_cents":1200,"payment_method":"offline",
                 "payment_timing":"on_delivery","expected_version":%d}
                """.formatted(version), 201);
        long agreement = proposed.at("/agreement/id").asLong();
        version = tradeVersion(buyer, trade);
        var accepted = http.post(buyer, "/trades/" + trade + "/agreements/" + agreement + "/decisions",
                "{\"decision\":\"accept\",\"expected_version\":" + version + "}", 200);
        assertThat(accepted.at("/trade/agreement/current/id").asString())
                .isEqualTo(Long.toString(agreement));
        return agreement;
    }

    private int tradeVersion(Session session, long trade) throws Exception {
        return http.get(session, "/trades/" + trade, 200).path("version").asInt();
    }

    private long publicProduct(String title) {
        return http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 1200, 'public') returning product_id
                """).param(http.accountId(seller)).param(title).query(Long.class).single();
    }
}
