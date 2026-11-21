package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;

/**
 * Work for one case decision. The trusted caller supplies the application time; it does not
 * participate in the idempotency digest.
 */
public record EnforcementCommand(long caseId, List<EnforcementInstruction> enforcements,
                                 List<Long> basisRefs, List<Long> evidenceFileIds, String reason, Instant occurredAt) {
    public EnforcementCommand {
        if (caseId <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "事项标识无效");
        }
        Objects.requireNonNull(enforcements);
        Objects.requireNonNull(evidenceFileIds);
        enforcements = List.copyOf(enforcements);
        if (enforcements.isEmpty()) {
            throw new BusinessError("INPUT_INVALID", 422, "执行项不能为空");
        }
        basisRefs = orderedIds(basisRefs);
        evidenceFileIds = orderedIds(evidenceFileIds);
        if (basisRefs.isEmpty()) {
            throw new BusinessError("BASIS_REQUIRED", 422, "处置依据不能为空");
        }
        if (reason == null || reason.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "处置理由不能为空");
        }
        Objects.requireNonNull(occurredAt);
        var ids = new HashSet<String>();
        for (var instruction : enforcements) {
            if (!ids.add(instruction.enforcementId())) {
                throw new BusinessError("INPUT_INVALID", 422, "执行标识不能重复");
            }
        }
    }

    private static List<Long> orderedIds(List<Long> ids) {
        if (ids.stream().anyMatch(id -> id == null || id <= 0)) {
            throw new BusinessError("INPUT_INVALID", 422, "证据标识无效");
        }
        return ids.stream().distinct().sorted().toList();
    }
}
