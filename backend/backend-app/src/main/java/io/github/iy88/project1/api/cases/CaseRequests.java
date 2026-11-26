package io.github.iy88.project1.api.cases;

import java.util.List;

/** JSON request bodies of the case lifecycle API. Global SNAKE_CASE naming applies. */
public final class CaseRequests {
    private CaseRequests() {
    }

    public record Target(String targetType, String targetId, String conversationKind, String conversationId,
                         String sourceProductId) {
    }

    public record Attachment(String fileId) {
    }

    public record Report(Target target, String reason, String note, List<Attachment> attachments) {
    }

    public record Supplement(String note, List<Attachment> attachments) {
    }

    public record Inquiry(String peerAccountId, String scopeText) {
    }

    public record EvidenceReference(String conversationKind, String conversationId, String messageId) {
    }

    public record ThreadRef(String conversationKind, String conversationId) {
    }

    public record Message(ThreadRef thread, String messageKind, String body, String inquiryActionId,
                          String appealActionId, String resolution, String basisRef,
                          String originalEnforcementId, List<Enforcement> replacementEnforcements) {
        /** Compatibility constructor for existing callers that do not select an execution. */
        public Message(ThreadRef thread, String messageKind, String body, String inquiryActionId,
                       String appealActionId, String resolution, String basisRef) {
            this(thread, messageKind, body, inquiryActionId, appealActionId, resolution, basisRef, null,
                    List.of());
        }

        /** Convenience constructor for a revoke that selects only the original execution. */
        public Message(ThreadRef thread, String messageKind, String body, String inquiryActionId,
                       String appealActionId, String resolution, String basisRef,
                       String originalEnforcementId) {
            this(thread, messageKind, body, inquiryActionId, appealActionId, resolution, basisRef,
                    originalEnforcementId, List.of());
        }
    }

    public record Enforcement(String action, String targetType, String targetId, String expectedResult) {
    }

    public record Decision(String decisionKind, String reason, List<String> basisRefs,
                           List<Enforcement> enforcements) {
    }

    public record Publish(String publicSummary, String publicReason) {
    }

    public record Lift(String reason) {
    }
}
