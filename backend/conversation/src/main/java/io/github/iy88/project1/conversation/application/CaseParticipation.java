package io.github.iy88.project1.conversation.application;

/**
 * Read-only case projection; the case module owns claims and the appeal window.
 *
 * <p>The related account is part of the qualification because one case can expose one thread per
 * related user: the case module must confirm this specific thread's user (or the currently
 * authorised claimant manager) rather than treating any case relation as access to every thread.
 */
public interface CaseParticipation {
    boolean canAccess(long caseId, long relatedAccountId, long accountId);
}
