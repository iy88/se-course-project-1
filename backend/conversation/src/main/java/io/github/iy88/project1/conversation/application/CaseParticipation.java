package io.github.iy88.project1.conversation.application;

/** Read-only case projection; the case module owns claims and the appeal window. */
public interface CaseParticipation {
    boolean canAccess(long caseId, long accountId);
}
