package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import java.util.List;

/** HTTP-neutral request records for the lifecycle use cases. */
public final class CaseCommands {
    private CaseCommands() {
    }

    public record Target(String targetType, long targetId, String conversationKind, Long conversationId) {
        public Target {
            if (targetType == null || targetType.isBlank()) {
                throw new BusinessError("INPUT_INVALID", 422, "target_type 不能为空");
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

    public record Message(Long conversationId, String messageKind, String body, Long inquiryActionId,
                          Long appealActionId, String resolution, String basisRef) {
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
