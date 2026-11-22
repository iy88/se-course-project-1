package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.Set;
import java.util.UUID;
import tools.jackson.databind.JsonNode;

/**
 * Named cross-module ports. Each implementation must participate in the caller's transaction and
 * must not commit. The trade module owns only its own tables and rules.
 */
public final class TradePorts {
    private TradePorts() {
    }

    public record ProductState(long productId, long sellerId, long contentVersion, String lifecycleState,
                               Long occupancyTradeId, String title, String description,
                               long priceCents, List<String> categoryNames, List<Long> imageFileIds) {
        public ProductState {
            categoryNames = List.copyOf(categoryNames);
            imageFileIds = List.copyOf(imageFileIds);
        }

        public TradeModels.Snapshot snapshot(long tradeId, java.time.Instant capturedAt) {
            return new TradeModels.Snapshot(tradeId, productId, title, description, priceCents,
                    categoryNames, imageFileIds, capturedAt);
        }
    }

    public record AccountQualification(long accountId, boolean exists, boolean writeRestricted) {
    }

    public record AccountProfile(long accountId, String displayName, String avatarUrl) {
    }

    public record ProductSummary(String title, long priceCents) {
    }

    public interface Product {
        Optional<ProductState> read(long productId);

        Optional<ProductSummary> visibleSummary(long productId, long viewerId);

        ProductState lock(WriteTransaction transaction, long productId);

        void requireTradable(ProductState state, long buyerId);

        void requireNoOccupancy(ProductState state, long tradeId);

        void acquire(WriteTransaction transaction, ProductState state, long tradeId);

        /** Releases the specified holder and puts the product off shelf in the same transaction. */
        void release(WriteTransaction transaction, ProductState state, long tradeId, String reason);
    }

    public interface Accounts {
        /** Checked under the calling write's account lock, including idempotency replay. */
        void requireCurrentSession(ExecutionContext context);

        AccountQualification qualification(long accountId);

        Map<Long, AccountProfile> profiles(Set<Long> accountIds);
    }

    /**
     * Trade conversation boundary. The implementation records conversation row locks in the caller's
     * {@link WriteTransaction}; callers plan the conversation keys and must not wrap the lock call in
     * another {@code transaction.lock}. Append and archive use the row already locked in this
     * transaction or the row created by {@link #ensure} and never take a second lock.
     */
    public interface Conversation {
        long ensure(WriteTransaction transaction, long tradeId, long productId, long buyerId, long sellerId);

        OptionalLong find(long tradeId);

        /** Locks the conversation row and records that lock in the current write transaction. */
        void lockConversation(WriteTransaction transaction, long conversationId);

        void append(WriteTransaction transaction, long conversationId, UUID businessEventId, String eventType,
                    String body, ResourceRef sourceRef);

        void archive(WriteTransaction transaction, long conversationId, long tradeId, String reason);
    }

    public interface Cases {
        void lockAndValidate(WriteTransaction transaction, long caseId, long managerId,
                             long tradeId, String basisRef);

        long openTimeoutCase(WriteTransaction transaction, ExecutionContext context, long tradeId, String reason);
    }

    public interface Notifications {
        void register(WriteTransaction transaction, UUID businessEventId, String eventType,
                      long tradeId, Set<Long> recipients);
    }

    /** Read projection used by the conversation module. */
    public interface Participation {
        /** Returns the trade participants and status, or empty when the trade does not exist. */
        Optional<TradeModels.ConversationAccess> findConversationAccess(long tradeId);

        TradeModels.ConversationAccess conversationAccess(long tradeId);

        boolean pairFrozen(long firstAccountId, long secondAccountId);
    }

    /** Read projection used by the evaluation module (API-TRD-012/015 owner). */
    public interface ReviewEligibility {
        TradeModels.ReviewEligibility reviewEligibility(long tradeId, long reviewerId);
    }

    public record GovernanceOutcome(long tradeId, String status, String phase, int version,
                                    String terminalReason) {
    }

    /** Same-transaction governance capabilities; the case module keeps its own idempotency entry. */
    public interface GovernanceTransaction {
        LockPlan governancePlan(long managerId, long tradeId, long caseId, boolean product);

        GovernanceOutcome freezeInTransaction(WriteTransaction transaction, ExecutionContext context, long caseId,
                                              long tradeId, String basisRef, String reason);

        GovernanceOutcome liftFreezeInTransaction(WriteTransaction transaction, ExecutionContext context,
                                                  long caseId, long tradeId, long freezeId, String basisRef,
                                                  String reason);

        GovernanceOutcome adjustStatusInTransaction(WriteTransaction transaction, ExecutionContext context,
                                                    long caseId, long tradeId, String targetStatus, String basisRef,
                                                    String reason);

        GovernanceOutcome restoreInTransaction(WriteTransaction transaction, ExecutionContext context, long caseId,
                                               long tradeId, String basisRef, String reason);

        GovernanceOutcome resolveDisputeInTransaction(WriteTransaction transaction, ExecutionContext context,
                                                      long caseId, long disputeId, String basisRef, String reason);
    }

    /** Named governance commands called by the case module with its own idempotency key. */
    public interface Governance {
        WriteResult<JsonNode> freeze(ExecutionContext context, String key, TradeCommands.Freeze command);

        WriteResult<JsonNode> liftFreeze(ExecutionContext context, String key, TradeCommands.LiftFreeze command);

        WriteResult<JsonNode> adjustStatus(ExecutionContext context, String key, TradeCommands.AdjustStatus command);

        WriteResult<JsonNode> restore(ExecutionContext context, String key, TradeCommands.Restore command);

        WriteResult<JsonNode> resolveDisputeAsAdmin(ExecutionContext context, String key,
                                                    TradeCommands.ResolveDispute command);
    }

    /** Product/account modules trigger these while holding their own WriteTransaction and plan. */
    public interface Closure {
        LockPlan productClosurePlan(long productId);

        LockPlan accountBanPlan(long accountId);

        void closePendingForProduct(WriteTransaction transaction, LockPlan plan, long productId,
                                    TradeVocabulary.CloseReason reason, String basisRef);

        void applyAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                             long restrictionId, String reason, String basisRef);

        void removeAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                              long restrictionId, String basisRef);
    }
}
