package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import java.util.Locale;
import java.util.Set;

/**
 * The enforcement actions confirmed for the governance use case. Subject modules own the
 * authoritative account, product, trade and conversation state; this enum only names the
 * orchestration entry and its target and result reference types.
 */
public enum EnforcementAction {
    RESTRICT_ACCOUNT(Set.of("account"), Set.of("account_restriction")),
    LIFT_ACCOUNT_RESTRICTION(Set.of("account"), Set.of("account_restriction")),
    WITHDRAW_PUBLIC_ACCESS(Set.of("product"), Set.of("product_display_restriction")),
    RESTORE_DISPLAY(Set.of("product"), Set.of("product_display_restriction")),
    REMOVE_CONTENT(Set.of("comment", "evaluation"), Set.of("comment", "evaluation")),
    FREEZE_TRADE(Set.of("trade"), Set.of("trade_transition")),
    LIFT_TRADE_FREEZE(Set.of("trade"), Set.of("trade_transition")),
    ADJUST_TRADE_STATUS(Set.of("trade"), Set.of("trade_transition")),
    REMOVE_EVALUATION_CONTENT(Set.of("evaluation"), Set.of("evaluation"));

    private final Set<String> targetTypes;
    private final Set<String> resultTypes;

    EnforcementAction(Set<String> targetTypes, Set<String> resultTypes) {
        this.targetTypes = Set.copyOf(targetTypes);
        this.resultTypes = Set.copyOf(resultTypes);
    }

    public String operationName() {
        return "case.enforcement." + name().toLowerCase(Locale.ROOT);
    }

    public void requireTarget(ResourceRef target) {
        if (target == null || !targetTypes.contains(target.type())) {
            throw new BusinessError("TARGET_INVALID", 422, "执行目标与动作不匹配");
        }
    }

    void requireResult(ResourceRef target, ResourceRef result) {
        if (result == null || !resultTypes.contains(result.type())) {
            throw new IllegalStateException("Subject returned an unexpected result type for " + name());
        }
        if ((this == REMOVE_CONTENT || this == REMOVE_EVALUATION_CONTENT)
                && !result.type().equals(target.type())) {
            throw new IllegalStateException("Content result type does not match the target for " + name());
        }
    }
}
