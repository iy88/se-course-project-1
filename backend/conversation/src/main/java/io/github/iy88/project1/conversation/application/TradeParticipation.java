package io.github.iy88.project1.conversation.application;

import java.util.List;
import java.util.Optional;

/**
 * Read-only trade projection required by conversations. The trade module owns the record and the
 * two-party freeze state; conversation code never writes trade data.
 */
public interface TradeParticipation {
    Optional<Participants> participants(long tradeId);

    /** True when an active trade freeze covers the account pair in either direction. */
    boolean pairFrozen(long firstAccountId, long secondAccountId);

    /** Trades in which the account is buyer or seller; used to assemble the conversation list. */
    List<Long> tradeIdsOf(long accountId);

    /**
     * Returns the public {@code type:id} reference only when the record is one of the trade-owned
     * source kinds and belongs to {@code tradeId}. Missing, unknown and cross-trade records must
     * stay hidden.
     */
    Optional<String> visibleSourceRef(long tradeId, String sourceType, Long sourceId);

    record Participants(long buyerId, long sellerId) {
        public Participants {
            if (buyerId <= 0 || sellerId <= 0 || buyerId == sellerId) {
                throw new IllegalArgumentException("A trade needs two distinct accounts");
            }
        }

        public boolean involves(long accountId) {
            return accountId == buyerId || accountId == sellerId;
        }

        public long peerOf(long accountId) {
            if (accountId == buyerId) {
                return sellerId;
            }
            if (accountId == sellerId) {
                return buyerId;
            }
            throw new IllegalArgumentException("Account does not participate in this trade");
        }
    }
}
