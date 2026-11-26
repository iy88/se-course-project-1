package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.OptionalLong;
import java.util.Set;

/**
 * Cross-module ports owned by the case lifecycle. Implementations participate in the caller's
 * transaction and never commit; account, product, trade, conversation, file and notification
 * facts stay with their own modules.
 */
public final class CasePorts {
    private CasePorts() {
    }

    /** Validates report targets and projects their related accounts. */
    public interface Targets {
        /** Rejects unknown, missing, self or unauthorized targets with the named case errors. */
        void requireReportable(CaseCommands.Target target, long reporterAccountId);

        /** Accounts that may be inquired and disposed for this case. */
        Set<Long> relatedAccountIds(CaseRecords.Facts facts);

        /** Buyer and seller of one trade, or an empty set when it does not exist. */
        Set<Long> tradeParties(long tradeId);
    }

    /** Account-owned management qualification. */
    public interface Managers {
        /** Session and role check for reads and for the first claim candidate. */
        void requireManager(ExecutionContext context);

        /** Rechecks the current session and role under the account and Session locks. */
        void requireManagerForWrite(ExecutionContext context);
    }

    public interface Accounts {
        boolean exists(long accountId);

        boolean writeRestricted(long accountId);
    }

    @FunctionalInterface
    public interface Notifications {
        void create(WriteTransaction transaction, String eventType, String intentKey, ResourceRef source,
                    Set<Long> recipients, Map<String, String> params, Instant occurredAt);
    }

    /** Case thread capability implemented on top of the conversation module. */
    public interface Threads {
        long ensure(WriteTransaction transaction, long caseId, long relatedAccountId);

        CaseRecords.ThreadMessage append(WriteTransaction transaction, long caseId, long relatedAccountId,
                                         String messageKind, String senderKind, long senderAccountId, String body);

        boolean archive(WriteTransaction transaction, long caseId, long relatedAccountId);

        OptionalLong findConversation(long caseId, long relatedAccountId);
    }

    /** Case evidence files, registered through the shared file service. */
    public interface EvidenceFiles {
        void lockFile(long fileId);

        /** Registers each verified file against the case and returns the file reference ids. */
        List<Long> attach(WriteTransaction transaction, long caseId, long submitterId, List<Long> fileIds);
    }

    /**
     * Subject execution for decided enforcement items. The adapter owns the subject locks and
     * returns the named outcome; the case store persists the links in the same transaction.
     */
    public interface Enforcement {
        LockPlan plan(ExecutionContext context, long caseId, List<CaseRecords.EnforcementInstruction> instructions);

        List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction, ExecutionContext context,
                                                     long caseId, String reason, String basisRef,
                                                     List<CaseRecords.EnforcementInstruction> instructions,
                                                     Instant occurredAt);

        /**
         * Reverses or adjusts one recorded enforcement for an appeal or an explicit lift. The
         * adapter resolves the subject record from the case source (never from a client-supplied
         * freeze id) and returns the compensating outcome. Adapters delivered by S4-01 (#81)
         * implement this; until then the default keeps the action unavailable instead of faking
         * success.
         */
        default List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction,
                                                             ExecutionContext context, long caseId,
                                                             CaseRecords.Enforcement recorded, String resolution,
                                                             String basisRef, String reason, Instant occurredAt) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "撤销或调整须由处置执行提供");
        }

        /**
         * Locks required by {@link #reverse}. The case lock is added by the caller; adapters add
         * subject locks in the public order so a reversal composes with the write transaction.
         */
        default LockPlan reversePlan(ExecutionContext context, long caseId, CaseRecords.Enforcement recorded,
                                     String resolution) {
            return new LockPlan(Map.of(), Set.of());
        }
    }
}
