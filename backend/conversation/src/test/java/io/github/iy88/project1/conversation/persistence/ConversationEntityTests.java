package io.github.iy88.project1.conversation.persistence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class ConversationEntityTests {
    private static final Instant NOW = Instant.parse("2026-11-22T10:00:00Z");

    @Test
    void chatAllocatesContiguousSequencesAndResolvesTheOtherAccount() {
        var conversation = new ChatConversation(7L, 42L, NOW);

        assertThat(conversation.allocateSeq()).isEqualTo(1L);
        assertThat(conversation.allocateSeq()).isEqualTo(2L);
        assertThat(conversation.seqHead()).isEqualTo(2L);
        assertThat(conversation.otherAccount(7L)).isEqualTo(42L);
        assertThat(conversation.otherAccount(42L)).isEqualTo(7L);
        assertThat(conversation.involves(9L)).isFalse();
    }

    @Test
    void chatRejectsUnorderedParticipants() {
        assertThatThrownBy(() -> new ChatConversation(42L, 7L, NOW))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void tradeArchiveIsOneWayAndBlocksFurtherSequences() {
        var conversation = new TradeConversation(11L, NOW);
        assertThat(conversation.allocateSeq()).isEqualTo(1L);

        assertThat(conversation.archive(NOW)).isTrue();
        assertThat(conversation.archive(NOW.plusSeconds(1))).isFalse();
        assertThat(conversation.archived()).isTrue();
        assertThatThrownBy(conversation::allocateSeq).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void readCursorOnlyMovesForward() {
        var progress = new ChatReadProgress(1L, 7L);

        assertThat(progress.advanceTo(4L, NOW)).isEqualTo(4L);
        assertThat(progress.advanceTo(2L, NOW.plusSeconds(1))).isEqualTo(4L);
        assertThat(progress.lastReadAt()).isEqualTo(NOW);
        assertThat(progress.advanceTo(6L, NOW.plusSeconds(2))).isEqualTo(6L);
        assertThat(progress.lastReadAt()).isEqualTo(NOW.plusSeconds(2));
    }
}
