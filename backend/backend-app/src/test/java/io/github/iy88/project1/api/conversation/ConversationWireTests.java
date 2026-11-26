package io.github.iy88.project1.api.conversation;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.conversation.ConversationKind;
import io.github.iy88.project1.conversation.application.ConversationViews;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class ConversationWireTests {
    private static final Instant NOW = Instant.parse("2026-11-23T10:00:00Z");

    @Test
    void chatAndTradeMessagesKeepMessageIdAndType() {
        var page = new ConversationViews.MessagePage(List.of(
                new ConversationViews.Message(21L, 2L,
                        new ConversationViews.Sender(7L, "张新悦", "account"),
                        "text", "在吗", NOW, null, null)), 2L, 2L, "active", 19L);

        var body = ConversationWire.messagePage(page, ConversationKind.TRADE);
        assertThat(body).containsEntry("trade_id", "19");

        @SuppressWarnings("unchecked")
        var item = (java.util.Map<String, Object>) ((List<?>) body.get("items")).getFirst();
        assertThat(item).containsEntry("message_id", "21").containsEntry("message_type", "text")
                .doesNotContainKey("case_message_id");
    }

    @Test
    void systemMessageSourceRefUsesThePublicResourceRefShape() {
        var page = new ConversationViews.MessagePage(List.of(
                new ConversationViews.Message(22L, 3L,
                        new ConversationViews.Sender(null, "系统", "system"),
                        "system_event", "交易已完成", NOW, "trade_completed", "trade_transition:55")),
                3L, 3L, "active", 19L);

        var body = ConversationWire.messagePage(page, ConversationKind.TRADE);

        @SuppressWarnings("unchecked")
        var item = (java.util.Map<String, Object>) ((List<?>) body.get("items")).getFirst();
        assertThat(item).containsEntry("source_ref", java.util.Map.of(
                "resource_type", "trade_transition", "resource_id", "55"));
    }

    @Test
    void caseMessagesUseTheCaseIdAndKindNames() {
        var page = new ConversationViews.MessagePage(List.of(
                new ConversationViews.Message(31L, 1L,
                        new ConversationViews.Sender(7L, "张新悦", "account"),
                        "statement", "说明", NOW, null, null)), 1L, 1L, "archived", null);

        var body = ConversationWire.messagePage(page, ConversationKind.CASE);

        @SuppressWarnings("unchecked")
        var item = (java.util.Map<String, Object>) ((List<?>) body.get("items")).getFirst();
        assertThat(item).containsEntry("case_message_id", "31").containsEntry("message_kind", "statement")
                .doesNotContainKey("message_id");
        assertThat(body).containsEntry("branch_status", "archived").doesNotContainKey("trade_id");
    }

    @Test
    void startedChatMarksTheKindAndPeer() {
        var body = ConversationWire.started(new ConversationViews.StartedChat(
                5L, 42L, "李四", "https://img.example/peer.png", true));

        assertThat(body).containsEntry("conversation_kind", "chat").containsEntry("conversation_id", "5")
                .containsEntry("reused", true);
        assertThat(body.get("peer")).isEqualTo(java.util.Map.of(
                "account_id", "42",
                "display_name", "李四",
                "avatar_url", "https://img.example/peer.png"));
    }
}
