package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.core.BusinessError;
import java.util.List;

/** HTTP-neutral request records for the lifecycle use cases. */
public final class CaseCommands {
    private CaseCommands() {
    }

    public record Target(String targetType, long targetId, String conversationKind, Long conversationId,
                         Long sourceProductId) {
        public Target(String targetType, long targetId, String conversationKind, Long conversationId) {
            this(targetType, targetId, conversationKind, conversationId, null);
        }

        public Target {
            if (targetType == null || targetType.isBlank()) {
                throw new BusinessError("INPUT_INVALID", 422, "target_type 不能为空");
            }
            if (sourceProductId != null && (!"account".equals(targetType) || sourceProductId <= 0)) {
                throw new BusinessError("TARGET_INVALID", 422, "来源商品无效");
            }
            if (targetId <= 0) {
                throw new BusinessError("TARGET_INVALID", 422, "目标对象无效");
            }
            if (("message".equals(targetType)) != (conversationKind != null && conversationId != null)) {
                throw new BusinessError("INPUT_INVALID", 422, "消息对象须同时给出会话类型与标识");
            }
        }
    }

    public record Report(Target target, String reason, String note, List<Long> attachments) {
        public Report {
            attachments = attachments == null ? List.of() : List.copyOf(attachments);
        }
    }

    public record Supplement(String note, List<Long> attachments) {
        public Supplement {
            attachments = attachments == null ? List.of() : List.copyOf(attachments);
        }
    }

    public record Inquiry(long peerAccountId, String scopeText) {
    }

    /** A platform-record reference must name the real branch and message, never a bare id. */
    public record EvidenceReference(String conversationKind, long conversationId, long messageId) {
        public EvidenceReference {
            if (!CaseVocabulary.CONVERSATION_KINDS.contains(conversationKind)) {
                throw new BusinessError("INPUT_INVALID", 422, "conversation_kind 取值无效");
            }
            if (conversationId <= 0 || messageId <= 0) {
                throw new BusinessError("INPUT_INVALID", 422, "消息引用标识无效");
            }
        }
    }

    /**
     * One case-thread message. {@code originalEnforcementId} is the manager-selected original
     * execution being revoked or adjusted; {@code replacementEnforcements} is only valid for an
     * adjustment and uses the same fields as a decision enforcement item.
     */
    public record Message(Long conversationId, String messageKind, String body, Long inquiryActionId,
                          Long appealActionId, String resolution, String basisRef,
                          String originalEnforcementId, List<Enforcement> replacementEnforcements) {
        public Message {
            replacementEnforcements = replacementEnforcements == null ? List.of()
                    : List.copyOf(replacementEnforcements);
        }

        /** Compatibility constructor for callers that do not select an original execution. */
        public Message(Long conversationId, String messageKind, String body, Long inquiryActionId,
                       Long appealActionId, String resolution, String basisRef) {
            this(conversationId, messageKind, body, inquiryActionId, appealActionId, resolution, basisRef,
                    null, List.of());
        }

        /** Convenience constructor for a revoke that selects only the original execution. */
        public Message(Long conversationId, String messageKind, String body, Long inquiryActionId,
                       Long appealActionId, String resolution, String basisRef, String originalEnforcementId) {
            this(conversationId, messageKind, body, inquiryActionId, appealActionId, resolution, basisRef,
                    originalEnforcementId, List.of());
        }
    }

    public record Decision(String decisionKind, String reason, List<String> basisRefs, List<Enforcement> enforcements) {
        public Decision {
            basisRefs = basisRefs == null ? List.of() : List.copyOf(basisRefs);
            enforcements = enforcements == null ? List.of() : List.copyOf(enforcements);
        }
    }

    public record Enforcement(String action, String targetType, long targetId, String expectedResult) {
    }

    public record Publish(String summary, String reason) {
    }
}
