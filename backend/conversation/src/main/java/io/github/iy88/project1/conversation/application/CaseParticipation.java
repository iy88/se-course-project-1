package io.github.iy88.project1.conversation.application;

/**
 * Read-only case projection; the case module owns claims and the appeal window.
 *
 * <p>The related account is part of the qualification because one case can expose one thread per
 * related user: the case module must confirm this specific thread's user (or the currently
 * authorised claimant manager) rather than treating any case relation as access to every thread.
 */
public interface CaseParticipation {
    /**
     * Authorizes the specific case thread. Access belongs to its related account or to a currently eligible
     * assigned manager; the case module supplies the real adapter and there is no fallback grant.
     */
    boolean canAccess(long caseId, long relatedAccountId, long actorAccountId);
}
