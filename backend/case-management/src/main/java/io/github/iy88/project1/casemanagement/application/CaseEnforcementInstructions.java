package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

/**
 * Validates decision and adjustment input and materialises enforcement instructions.
 *
 * <p>Validation order, error precedence and identifier generation stay at their original points,
 * so callers observe the same failures and one generated identifier per accepted instruction.</p>
 */
final class CaseEnforcementInstructions {
    private static final Set<String> ENFORCEMENT_ACTIONS = Set.of(
            "restrict_account", "lift_account_restriction", "withdraw_public_access", "restore_display",
            "remove_content", "freeze_trade", "lift_trade_freeze", "adjust_trade_status",
            "remove_evaluation_content");
    private static final Set<String> TRADE_ACTIONS = Set.of("freeze_trade", "lift_trade_freeze",
            "adjust_trade_status");
    private static final Set<String> ADJUST_TRADE_TARGETS = Set.of("completed", "terminated", "in_progress");

    private CaseEnforcementInstructions() {
    }

    static List<CaseRecords.EnforcementInstruction> instructions(CaseCommands.Decision decision) {
        return instructions(decision.enforcements());
    }

    static List<CaseRecords.EnforcementInstruction> instructions(List<CaseCommands.Enforcement> enforcements) {
        var list = new ArrayList<CaseRecords.EnforcementInstruction>();
        for (var item : enforcements) {
            if (item.action() == null || !ENFORCEMENT_ACTIONS.contains(item.action())) {
                throw new BusinessError("INPUT_INVALID", 422, "执行动作无效");
            }
            if (item.targetType() == null || item.targetType().isBlank() || item.targetId() <= 0) {
                throw new BusinessError("TARGET_INVALID", 422, "执行目标无效");
            }
            if (TRADE_ACTIONS.contains(item.action()) && !"trade".equals(item.targetType())) {
                throw new BusinessError("TARGET_INVALID", 422, "交易动作的目标无效");
            }
            String expected = item.expectedResult();
            if ("adjust_trade_status".equals(item.action())) {
                if (expected == null || expected.isBlank()) {
                    throw new BusinessError("INPUT_INVALID", 422, "调整交易状态须给出目标状态");
                }
                expected = expected.trim().toLowerCase(Locale.ROOT);
                if (!ADJUST_TRADE_TARGETS.contains(expected)) {
                    throw new BusinessError("INPUT_INVALID", 422, "调整交易状态的目标无效");
                }
            }
            list.add(new CaseRecords.EnforcementInstruction(UUID.randomUUID().toString(), item.action(),
                    item.targetType(), item.targetId(), expected));
        }
        return list;
    }

    /**
     * A replacement must stay on the original target and name a new concrete action. This keeps
     * an adjustment from becoming an arbitrary account/product/trade selection or a hidden lift.
     */
    static List<CaseRecords.EnforcementInstruction> replacementInstructions(CaseCommands.Message message,
                                                                              CaseRecords.Enforcement recorded) {
        var replacements = instructions(message.replacementEnforcements());
        for (var item : replacements) {
            if (!recorded.targetType().equals(item.targetType()) || recorded.targetId() != item.targetId()) {
                throw new BusinessError("INPUT_INVALID", 422, "调整处置须沿用原处置目标");
            }
            if (CaseApplication.LIFT_ACTIONS.contains(item.action())) {
                throw new BusinessError("INPUT_INVALID", 422, "调整处置须给出新的处置动作");
            }
        }
        return replacements;
    }

    /** A subject execution may only target the trade recorded as this case's target. */
    static void requireTradeTargets(CaseRecords.Facts facts,
                                    List<CaseRecords.EnforcementInstruction> instructions) {
        for (var item : instructions) {
            if (!TRADE_ACTIONS.contains(item.action())) {
                continue;
            }
            if (!"trade".equals(facts.targetType()) || facts.targetId() == null
                    || facts.targetId() != item.targetId()) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项目标与交易不一致");
            }
        }
    }

    /** A recorded trade enforcement must still point at this case's current target trade. */
    static void requireRecordedTarget(CaseRecords.Facts facts, CaseRecords.Enforcement recorded) {
        if (!"trade".equals(recorded.targetType())) {
            return;
        }
        if (!"trade".equals(facts.targetType()) || facts.targetId() == null
                || facts.targetId() != recorded.targetId()) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项与执行记录的目标不一致");
        }
    }
}
