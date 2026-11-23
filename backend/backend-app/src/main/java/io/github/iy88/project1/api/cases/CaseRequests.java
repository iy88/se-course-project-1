package io.github.iy88.project1.api.cases;

import java.util.List;

/** JSON request bodies of the case lifecycle API. Global SNAKE_CASE naming applies. */
public final class CaseRequests {
    private CaseRequests() {
    }

    public record Target(String targetType, String targetId, String conversationKind, String conversationId) {
    }

    public record Attachment(String fileId) {
    }

    public record Report(Target target, String reason, String note, List<Attachment> attachments) {
    }

    public record Supplement(String note, List<Attachment> attachments) {
    }

    public record Inquiry(String peerAccountId, String scopeText) {
    }

    public record ThreadRef(String conversationKind, String conversationId) {
    }

    public record Message(ThreadRef thread, String messageKind, String body, String inquiryActionId,
                          String appealActionId, String resolution, String basisRef) {
    }

    public record Enforcement(String action, String targetType, String targetId, String expectedResult) {
    }

    public record Decision(String decisionKind, String reason, List<String> basisRefs,
                           List<Enforcement> enforcements) {
    }

    public record Publish(String publicSummary, String publicReason) {
    }
}
