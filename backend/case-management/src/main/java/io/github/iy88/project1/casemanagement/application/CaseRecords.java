package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** Immutable lifecycle records shared by the store, the use cases and the query side. */
public final class CaseRecords {
    private CaseRecords() {
    }

    /** One persisted case row. Product-review rows leave the lifecycle fields empty. */
    public record Facts(long caseId, String caseType, String targetType, Long targetId,
                        String conversationKind, Long conversationId, Long reporterAccountId,
                        String reportedReason, Long claimedManagerId, Instant claimedAt, String caseStatus,
                        String decisionKind, String reasonText, Long decidedBy, Instant decidedAt,
                        Instant archivedAt, String publicSummary, String publicReason,
                        Instant publicResultAt, Instant createdAt, Instant updatedAt) {
        public boolean archived() {
            return archivedAt != null;
        }

        public boolean decided() {
            return CaseVocabulary.DECIDED.equals(caseStatus);
        }

        public boolean lifecycle() {
            return CaseVocabulary.isLifecycle(caseType);
        }

        public boolean claimedBy(long accountId) {
            return claimedManagerId != null && claimedManagerId == accountId;
        }

        public boolean reportedBy(long accountId) {
            return reporterAccountId != null && reporterAccountId == accountId;
        }
    }

    /** One append-only case action. */
    public record Action(long actionId, long caseId, String actionKind, String actorKind, Long actorAccountId,
                         Instant occurredAt, Long messageId, Long relatedAccountId, Long inquiryActionId,
                         Long appealActionId, String resolution, String note, String basisRef) {
    }

    public record Evidence(long evidenceId, long caseId, String evidenceKind, Long fileId, Long referenceId,
                           String sourceRefType, Long sourceRefId, String requiredScope, Long submittedBy,
                           Instant submittedAt) {
    }

    /** Minimal message facts returned for one manager-authorised platform-record reference. */
    public record ReferencedMessage(long messageId, String conversationKind, long conversationId,
                                    String senderKind, Long senderAccountId, String body, Instant createdAt) {
    }

    /**
     * The branch scope stored with a message reference. The scope is the only location hint kept
     * beside the source resource id, so reading always re-checks the real message against it.
     */
    public record MessageScope(String conversationKind, long conversationId) {
        public MessageScope {
            if (!CaseVocabulary.CONVERSATION_KINDS.contains(conversationKind) || conversationId <= 0) {
                throw new IllegalArgumentException("Invalid message scope");
            }
        }

        public static String format(String conversationKind, long conversationId) {
            return new MessageScope(conversationKind, conversationId).value();
        }

        public static Optional<MessageScope> parse(String value) {
            if (value == null) {
                return Optional.empty();
            }
            int separator = value.indexOf(':');
            if (separator <= 0 || separator == value.length() - 1) {
                return Optional.empty();
            }
            try {
                return Optional.of(new MessageScope(value.substring(0, separator),
                        Long.parseLong(value.substring(separator + 1))));
            } catch (IllegalArgumentException invalid) {
                return Optional.empty();
            }
        }

        public String value() {
            return conversationKind + ":" + conversationId;
        }
    }

    public record AppealEligibility(long caseId, long accountId, Instant appealDeadlineAt, String basisRef) {
    }

    /** One persisted enforcement request and its subject result; {@code liftedAt} is null until reverted. */
    public record Enforcement(String enforcementId, long caseId, String action, String targetType, long targetId,
                              String basisRef, long requestedBy, Instant requestedAt, String resultType,
                              Long resultId, String resultStatus, String previousState, String currentState,
                              List<Long> affectedAccountIds, String failureCode, String failureReason,
                              Instant occurredAt, Instant liftedAt) {
        public Enforcement {
            affectedAccountIds = List.copyOf(affectedAccountIds);
        }
    }

    /** One thread created for a related account. */
    public record Thread(long conversationId, long caseId, long relatedAccountId) {
    }

    /** Lift facts of one enforcement record. */
    public record Lift(Instant liftedAt, long liftedBy) {
    }

    public record ThreadMessage(long conversationId, long messageId, long seq, Instant createdAt) {
    }

    public record Append(String caseId, String caseType) {
    }

    /** Result of one subject enforcement call, before it is persisted. */
    public record EnforcementOutcome(String enforcementId, String action, String targetType, long targetId,
                                     String resultType, Long resultId, String resultStatus, String previousState,
                                     String currentState, List<Long> affectedAccountIds, Instant occurredAt,
                                     List<String> remainingRestrictions) {
        public EnforcementOutcome {
            affectedAccountIds = List.copyOf(affectedAccountIds);
            remainingRestrictions = List.copyOf(remainingRestrictions);
        }

        public EnforcementOutcome(String enforcementId, String action, String targetType, long targetId,
                                  String resultType, Long resultId, String resultStatus, String previousState,
                                  String currentState, List<Long> affectedAccountIds, Instant occurredAt) {
            this(enforcementId, action, targetType, targetId, resultType, resultId, resultStatus,
                    previousState, currentState, affectedAccountIds, occurredAt, List.of());
        }
    }

    /** Instructions generated by the decision use case for the subject adapter. */
    public record EnforcementInstruction(String enforcementId, String action, String targetType, long targetId,
                                         String expectedResult) {
    }
}
