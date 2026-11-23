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
                        "text", "在吗", NOW, null, null)), 2L, 2L, "active");

        var body = ConversationWire.messagePage(page, ConversationKind.TRADE);

        @SuppressWarnings("unchecked")
        var item = (java.util.Map<String, Object>) ((List<?>) body.get("items")).getFirst();
        assertThat(item).containsEntry("message_id", "21").containsEntry("message_type", "text")
                .doesNotContainKey("case_message_id");
    }

    @Test
    void caseMessagesUseTheCaseIdAndKindNames() {
        var page = new ConversationViews.MessagePage(List.of(
                new ConversationViews.Message(31L, 1L,
                        new ConversationViews.Sender(7L, "张新悦", "account"),
                        "statement", "说明", NOW, null, null)), 1L, 1L, "archived");

        var body = ConversationWire.messagePage(page, ConversationKind.CASE);

        @SuppressWarnings("unchecked")
        var item = (java.util.Map<String, Object>) ((List<?>) body.get("items")).getFirst();
        assertThat(item).containsEntry("case_message_id", "31").containsEntry("message_kind", "statement")
                .doesNotContainKey("message_id");
        assertThat(body).containsEntry("branch_status", "archived");
    }

    @Test
    void startedChatMarksTheKindAndPeer() {
        var body = ConversationWire.started(new ConversationViews.StartedChat(5L, 42L, "李四", true));

        assertThat(body).containsEntry("conversation_kind", "chat").containsEntry("conversation_id", "5")
                .containsEntry("reused", true);
    }
}
