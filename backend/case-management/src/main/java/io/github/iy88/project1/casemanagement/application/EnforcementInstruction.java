package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import java.util.Objects;

/**
 * One entry issued by the case application. {@code enforcementId} is stable for the persisted
 * execution and is therefore safe to use for same-source replay and notification intent keys.
 * {@code detail} carries an action-specific secondary reference such as a restriction record.
 */
public record EnforcementInstruction(String enforcementId, EnforcementAction action, ResourceRef target,
                                     ResourceRef detail, String expectedResult) {
    public EnforcementInstruction {
        if (enforcementId == null || enforcementId.isBlank() || enforcementId.length() > 128) {
            throw new BusinessError("INPUT_INVALID", 422, "执行标识无效");
        }
        Objects.requireNonNull(action);
        action.requireTarget(target);
        if (expectedResult != null && expectedResult.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "执行预期结果不能为空");
        }
        if (action == EnforcementAction.ADJUST_TRADE_STATUS && expectedResult == null) {
            throw new BusinessError("INPUT_INVALID", 422, "调整交易状态须给出目标状态");
        }
        if (action == EnforcementAction.LIFT_ACCOUNT_RESTRICTION && detail == null) {
            throw new BusinessError("INPUT_INVALID", 422, "解除账户限制须给出限制记录");
        }
    }

    public static EnforcementInstruction of(String enforcementId, EnforcementAction action, ResourceRef target) {
        return new EnforcementInstruction(enforcementId, action, target, null, null);
    }
}
