package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import java.util.List;
import java.util.Objects;

/** Validated decision content submitted by a review manager. */
public record ReviewDecisionInput(long auditId, ReviewAction action, String reason,
                                  List<Long> bannedItemIds, ReviewAction categoryAction,
                                  String categoryReason) {
    public ReviewDecisionInput {
        if (auditId <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "审核标识无效");
        }
        Objects.requireNonNull(action);
        if (action == ReviewAction.REJECT && (reason == null || reason.isBlank())) {
            throw new BusinessError("INPUT_INVALID", 422, "审核结论理由不能为空");
        }
        Objects.requireNonNull(bannedItemIds);
        if (bannedItemIds.stream().anyMatch(id -> id == null || id <= 0)) {
            throw new BusinessError("INPUT_INVALID", 422, "审核依据无效");
        }
        bannedItemIds = bannedItemIds.stream().distinct().sorted().toList();
        if (categoryAction == ReviewAction.REJECT && (categoryReason == null || categoryReason.isBlank())) {
            throw new BusinessError("INPUT_INVALID", 422, "分类申请理由不能为空");
        }
    }
}
