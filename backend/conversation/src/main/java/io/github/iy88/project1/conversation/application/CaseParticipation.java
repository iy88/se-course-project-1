package io.github.iy88.project1.conversation.application;

/** Read-only case projection; the case module owns claims and the appeal window. */
public interface CaseParticipation {
    /**
     * Authorizes the specific case thread. Access belongs to its related account or to a currently eligible
     * assigned manager; the case module supplies the real adapter and there is no fallback grant.
     */
    boolean canAccess(long caseId, long relatedAccountId, long actorAccountId);
}
