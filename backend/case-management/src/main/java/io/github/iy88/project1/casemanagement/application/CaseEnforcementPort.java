package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.storage.persistence.FileReferences;
import java.util.List;

/**
 * Case-owned contract supplied by the case domain. It is the authority for claim, decision,
 * basis, evidence authorization, prior execution links and the failure trail. The application
 * never infers these facts from the caller or from a subject target.
 */
public interface CaseEnforcementPort {
    /** Read-only candidate collection used by the S1 prepare phase. */
    CaseAccess prepare(ExecutionContext context, EnforcementCommand command);

    /** Re-read the current manager and case read rights; used before every attempt, including replay. */
    CaseAccess requireManager(ExecutionContext context, EnforcementCommand command);

    /**
     * Re-reads the case under its row lock and verifies persisted execution IDs match the original
     * instruction and basis before reusing prior outcomes.
     */
    CaseAccess revalidate(WriteTransaction transaction, ExecutionContext context, EnforcementCommand command,
                          CaseAccess current);

    /** Full decision/claim/basis check; skipped only when every entry already has a successful link. */
    void requireExecutable(WriteTransaction transaction, ExecutionContext context, EnforcementCommand command,
                           CaseAccess access);

    /** Lock the case row in the global CASE position. */
    void lockCase(WriteTransaction transaction, long caseId);

    /**
     * Persist the execute trail and result links in the current transaction. This runs under the
     * already-held CASE lock and must not acquire a new resource lock key.
     */
    void recordExecution(WriteTransaction transaction, ExecutionContext context, EnforcementCommand command,
                         List<EnforcementOutcome> outcomes, List<FileReferences.Reference> references);

    /** Current management and case read rights for an S1 result replay. */
    void requireReplayAccess(ExecutionContext context, long caseId);

    /**
     * Case-owned failure trail. Callers invoke this only after {@code execute} threw and the
     * transaction rolled back, and only for genuine failed business execution; never for replay,
     * authorization or conflict errors. The adapter owns its own short transaction.
     */
    void recordFailure(ExecutionContext context, EnforcementCommand command, String errorCode, String message);
}
