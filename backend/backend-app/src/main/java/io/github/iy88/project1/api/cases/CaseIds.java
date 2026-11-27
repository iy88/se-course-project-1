package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.application.CaseCommands;
import io.github.iy88.project1.core.BusinessError;
import java.util.List;

/** HTTP id parsing and request-to-command conversion for the case API. */
final class CaseIds {
    private CaseIds() {
    }

    /** Path identifiers hide existence, so a malformed case id is a 404. */
    static long path(String value) {
        return parse(value, "RESOURCE_NOT_VISIBLE", 404);
    }

    /** Body identifiers report the field as invalid input. */
    static long body(String value, String field) {
        return parse(value, "INPUT_INVALID", 422, field);
    }

    private static long parse(String value, String code, int status) {
        return parse(value, code, status, "标识");
    }

    private static long parse(String value, String code, int status, String field) {
        try {
            long id = Long.parseLong(value);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared named error.
        }
        throw new BusinessError(code, status, field + "无效");
    }

    static CaseCommands.Target target(CaseRequests.Target target) {
        if (target == null) {
            throw new BusinessError("INPUT_INVALID", 422, "target 不能为空");
        }
        Long conversationId = target.conversationId() == null ? null
                : body(target.conversationId(), "conversation_id");
        return new CaseCommands.Target(target.targetType(), body(target.targetId(), "target_id"),
                target.conversationKind(), conversationId,
                target.sourceProductId() == null ? null : body(target.sourceProductId(), "source_product_id"));
    }

    static List<Long> attachments(List<CaseRequests.Attachment> attachments) {
        if (attachments == null) {
            return List.of();
        }
        return attachments.stream().map(attachment -> body(attachment.fileId(), "file_id")).toList();
    }

    static CaseCommands.Report report(CaseRequests.Report body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        return new CaseCommands.Report(target(body.target()), body.reason(), body.note(),
                attachments(body.attachments()));
    }

    static CaseCommands.Supplement supplement(CaseRequests.Supplement body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        return new CaseCommands.Supplement(body.note(), attachments(body.attachments()));
    }

    static CaseCommands.Inquiry inquiry(CaseRequests.Inquiry body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        return new CaseCommands.Inquiry(body(body.peerAccountId(), "peer_account_id"), body.scopeText());
    }

    static CaseCommands.EvidenceReference evidenceReference(CaseRequests.EvidenceReference body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        return new CaseCommands.EvidenceReference(body.conversationKind(),
                body(body.conversationId(), "conversation_id"), body(body.messageId(), "message_id"));
    }

    static CaseCommands.Message message(CaseRequests.Message body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        Long conversationId = null;
        if (body.thread() != null) {
            if (body.thread().conversationKind() != null && !"case".equals(body.thread().conversationKind())) {
                throw new BusinessError("INPUT_INVALID", 422, "thread.conversation_kind 取值无效");
            }
            if (body.thread().conversationId() != null) {
                conversationId = body(body.thread().conversationId(), "conversation_id");
            }
        }
        if (body.basisRefs() != null && (body.basisRef() != null
                || body.basisRefs().stream().anyMatch(ref -> ref == null || ref.isBlank()))) {
            throw new BusinessError("INPUT_INVALID", 422, "依据引用字段无效");
        }
        return new CaseCommands.Message(conversationId, body.messageKind(), body.body(),
                optionalId(body.inquiryActionId(), "inquiry_action_id"),
                optionalId(body.appealActionId(), "appeal_action_id"), body.resolution(), body.basisRef(),
                enforcementId(body.originalEnforcementId()), enforcements(body.replacementEnforcements()),
                body.basisRefs());
    }

    static CaseCommands.Decision decision(CaseRequests.Decision body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        return new CaseCommands.Decision(body.decisionKind(), body.reason(), body.basisRefs(),
                enforcements(body.enforcements()));
    }

    /**
     * The selected original execution is a case-stable opaque string, not a numeric resource id.
     * A blank value is treated as absent so the use case can name the missing field.
     */
    static String enforcementId(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim();
        if (trimmed.length() > 128) {
            throw new BusinessError("INPUT_INVALID", 422, "original_enforcement_id 无效");
        }
        return trimmed;
    }

    static List<CaseCommands.Enforcement> enforcements(List<CaseRequests.Enforcement> items) {
        if (items == null) {
            return List.of();
        }
        return items.stream().map(item -> {
            if (item == null) {
                throw new BusinessError("INPUT_INVALID", 422, "执行项不能为空");
            }
            return new CaseCommands.Enforcement(item.action(), item.targetType(),
                    body(item.targetId(), "target_id"), item.expectedResult());
        }).toList();
    }

    static CaseCommands.Publish publish(CaseRequests.Publish body) {
        if (body == null) {
            throw new BusinessError("INPUT_INVALID", 422, "请求体不能为空");
        }
        return new CaseCommands.Publish(body.publicSummary(), body.publicReason());
    }

    static Long optionalId(String value, String field) {
        return value == null || value.isBlank() ? null : body(value, field);
    }
}
