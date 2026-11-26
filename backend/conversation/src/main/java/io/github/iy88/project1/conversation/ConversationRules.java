package io.github.iy88.project1.conversation;

/** Pure rules shared by the three conversation tables. */
public final class ConversationRules {
    private ConversationRules() {
    }

    public record Pair(long lowAccountId, long highAccountId) {
        public Pair {
            if (lowAccountId <= 0 || highAccountId <= lowAccountId) {
                throw new IllegalArgumentException("Chat participants must be positive, ordered and distinct");
            }
        }
    }

    public static Pair pair(long firstAccountId, long secondAccountId) {
        if (firstAccountId == secondAccountId) {
            throw new IllegalArgumentException("A chat conversation needs two distinct accounts");
        }
        return firstAccountId < secondAccountId
                ? new Pair(firstAccountId, secondAccountId)
                : new Pair(secondAccountId, firstAccountId);
    }

    /** Read cursors only move forward; an out-of-order submission keeps the larger value. */
    public static long advancedReadSeq(long currentSeq, long displayedSeq) {
        if (displayedSeq < 0) {
            throw new IllegalArgumentException("Displayed sequence must not be negative");
        }
        return Math.max(currentSeq, displayedSeq);
    }

    /** Unread is derived from the head; it is never stored as an independent counter. */
    public static long unreadCount(long seqHead, long lastReadSeq) {
        if (seqHead < 0 || lastReadSeq < 0 || lastReadSeq > seqHead) {
            throw new IllegalArgumentException("Read progress must stay within the conversation");
        }
        return seqHead - lastReadSeq;
    }
}
