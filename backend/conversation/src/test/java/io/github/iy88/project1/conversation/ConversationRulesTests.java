package io.github.iy88.project1.conversation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class ConversationRulesTests {
    @Test
    void ordersParticipantPairRegardlessOfCallerOrder() {
        var pair = ConversationRules.pair(42L, 7L);

        assertThat(pair.lowAccountId()).isEqualTo(7L);
        assertThat(pair.highAccountId()).isEqualTo(42L);
    }

    @Test
    void rejectsSelfConversation() {
        assertThatThrownBy(() -> ConversationRules.pair(9L, 9L))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void keepsTheLargerReadCursor() {
        assertThat(ConversationRules.advancedReadSeq(5L, 3L)).isEqualTo(5L);
        assertThat(ConversationRules.advancedReadSeq(5L, 8L)).isEqualTo(8L);
    }

    @Test
    void derivesUnreadFromHeadAndCursor() {
        assertThat(ConversationRules.unreadCount(9L, 4L)).isEqualTo(5L);
        assertThat(ConversationRules.unreadCount(9L, 9L)).isZero();
    }

    @Test
    void rejectsCursorBeyondHead() {
        assertThatThrownBy(() -> ConversationRules.unreadCount(3L, 4L))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
