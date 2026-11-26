package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import java.time.Instant;
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

        /** Locks only the row for a caller that already declared and recorded the key. */
        void lockConversationRow(WriteTransaction transaction, long conversationId);

        void append(WriteTransaction transaction, long conversationId, UUID businessEventId, String eventType,
                    String body, ResourceRef sourceRef);

        void archive(WriteTransaction transaction, long conversationId, long tradeId, String reason);
    }

    public interface Cases {
        void lockAndValidate(WriteTransaction transaction, long caseId, long managerId,
                             long tradeId, String basisRef);

        long openTimeoutCase(WriteTransaction transaction, ExecutionContext context, long tradeId, String reason);

        /** Creates the shared exception case and its dispute link in the caller's transaction. */
        long openDisputeCase(WriteTransaction transaction, ExecutionContext context, long tradeId, long disputeId,
                             java.time.Instant at);

        /**
         * Case-owned plan for auto-closing one self-resolved dispute: the case row plus its
         * existing threads. A historical dispute without a case contributes no keys and must not
         * create a case here. The caller merges this plan with the trade and account plan.
         */
        default LockPlan prepareSelfResolution(long caseId) {
            return new LockPlan(Map.of(), Set.of());
        }

        /**
         * Locks and validates the case row before the caller locks the trade conversation. The
         * caller has already declared and acquired the CASE key; this method only re-reads the
         * locked row and verifies that the case is the dispute case of this trade.
         */
        default void lockSelfResolution(WriteTransaction transaction, long caseId, long tradeId, long disputeId) {
        }

        /**
         * Archives the case and its existing threads after the second distinct party confirms.
         * Thread locks are acquired in ascending id order. A thread missing from the prepared plan
         * surfaces as {@link LockPlan.Changed} so the whole transaction is replanned. An archived
         * case is left untouched to keep the stream single-write.
         */
        default void archiveSelfResolved(WriteTransaction transaction, long caseId, long tradeId, long disputeId,
                                         Instant at) {
        }
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

        /** Product carried by the trade, or empty when the trade does not exist. */
        OptionalLong productId(long tradeId);

        boolean pairFrozen(long firstAccountId, long secondAccountId);

        /** Ids of all trades where the account is buyer or seller, including terminal trades. */
        List<Long> tradeIdsOf(long accountId);
    }

    /** Read projection used by the evaluation module (API-TRD-012/015 owner). */
    public interface ReviewEligibility {
        TradeModels.ReviewEligibility reviewEligibility(long tradeId, long reviewerId);
    }

    public record GovernanceOutcome(long tradeId, String status, String phase, int version,
                                    String terminalReason) {
    }

    /** Read-only case-subject plan plus the exact rows the caller must lock before acting. */
    public record CaseEnforcementPlan(LockPlan lockPlan, long conversationId, Long productId) {
        public CaseEnforcementPlan {
            java.util.Objects.requireNonNull(lockPlan);
        }
    }

    /**
     * Trade-owned facts returned by one case enforcement path. {@code transitionId} is the
     * {@code trade_state_history} identifier used as the transition result reference.
     * {@code frozenBefore}/{@code frozenAfter} describe the trade's freeze state at the transition.
     */
    public record CaseEnforcementOutcome(long tradeId, long transitionId, UUID businessEventId,
                                         String previousStatus, String currentStatus,
                                         String previousPhase, String currentPhase, boolean frozenBefore,
                                         boolean frozenAfter, boolean alreadyEffective) {
        public ResourceRef transitionRef() {
            return new ResourceRef("trade_transition", transitionId);
        }
    }

    /**
     * Case-specific trade subject capability. The caller prepares a plan, locks the returned
     * product (terminal adjustment only), trade and trade-conversation rows once in
     * {@link LockPlan.Key} order together with its case lock. Action methods read current facts
     * under those locks and leave notifications, audit and conversation messages to
     * {@link #publishLocked}.
     */
    public interface CaseEnforcement {
        CaseEnforcementPlan prepare(long managerId, long tradeId, long caseId, boolean product);

        void lockTrade(WriteTransaction transaction, long tradeId);

        void lockConversation(WriteTransaction transaction, long conversationId);

        void lockCaseProduct(WriteTransaction transaction, long productId);

        /**
         * Locks only the trade row. The caller has already declared the TRADE key in its plan and
         * records the acquisition itself, so this method must not call
         * {@link WriteTransaction#lock}.
         */
        void lockTradeRow(WriteTransaction transaction, long tradeId);

        /**
         * Locks only the trade-conversation row. The caller has already declared the
         * TRADE_CONVERSATION key in its plan and records the acquisition itself.
         */
        void lockConversationRow(WriteTransaction transaction, long conversationId);

        /**
         * Locks only the product row. The caller has already declared the PRODUCT key in its plan
         * and records the acquisition itself.
         */
        void lockCaseProductRow(WriteTransaction transaction, long productId);

        CaseEnforcementOutcome freezeLocked(WriteTransaction transaction, long caseId, long tradeId,
                                            String basisRef, String reason);

        CaseEnforcementOutcome liftFreezeLocked(WriteTransaction transaction, long caseId,
                                                long tradeId, long freezeTransitionId, String basisRef,
                                                String reason);

        CaseEnforcementOutcome adjustStatusLocked(WriteTransaction transaction, long caseId,
                                                  long tradeId, String targetStatus,
                                                  String basisRef, String reason);

        CaseEnforcementOutcome restoreLocked(WriteTransaction transaction, long caseId, long tradeId,
                                             String basisRef, String reason);

        /**
         * Publishes the trade-owned effects of one already locked case enforcement: the trade
         * conversation system event, the two-party notification intent and the trade audit row.
         * It reuses the same effects as the normal governance commands and therefore must be
         * called at most once per action outcome; a replayed freeze publishes nothing.
         */
        void publishLocked(WriteTransaction transaction, long caseId, long tradeId, String action,
                           CaseEnforcementOutcome outcome, String reason);

        /**
         * Resolves the unique admin-case freeze transition for a legacy case enforcement that
         * stored the trade id in {@code result_id}. Matching is by explicit case source, trade,
         * freeze source and the freeze action; zero or multiple matches mean the original freeze
         * is not identifiable and the caller must fail closed instead of choosing a recent row.
         */
        long legacyFreezeTransition(long caseId, long tradeId);
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

        int closePendingForProduct(WriteTransaction transaction, LockPlan plan, long productId,
                                    TradeVocabulary.CloseReason reason, String basisRef);

        void applyAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                             long restrictionId, String reason, String basisRef);

        void removeAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                              long restrictionId, String basisRef);

        /**
         * Same mutations for callers that already acquired every trade and conversation row through
         * their own {@link SubjectPlan}. These methods never take a second lock; a candidate that
         * was not acquired raises {@link LockPlan.Changed} so the caller re-plans the whole batch.
         * The returned count is the number of changed trade facts.
         */
        int closePendingForProductLocked(WriteTransaction transaction, long productId,
                                         TradeVocabulary.CloseReason reason, String basisRef);

        int applyAccountBanLocked(WriteTransaction transaction, long accountId, long restrictionId,
                                  String reason, String basisRef);

        int removeAccountBanLocked(WriteTransaction transaction, long accountId, long restrictionId,
                                   String basisRef);

        /**
         * Whether an unended freeze still applies to this account as a party of a trade. The freeze
         * may be sourced by a timeout, an admin case or an account ban; every source freezes the
         * trade's buyer and seller, so both parties are restricted until that exact freeze ends.
         *
         * <p>This is a party qualification, not an account-ban read: it is used for starting a new
         * trade and for publishing, listing or actively delisting products. It must be read after
         * the caller holds the account qualification lock and in the caller's write transaction.</p>
         */
        boolean hasActivePartyFreeze(long accountId);

        /** Whether any trade involving the account still carries an active freeze. */
        boolean hasActiveAccountFreeze(long accountId);
    }
}
