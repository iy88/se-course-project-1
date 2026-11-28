package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Package-private helpers shared by the case write use cases. */
final class CaseWriteSupport {
    private CaseWriteSupport() {
    }

    static long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
    }

    static void requireLifecycle(CaseRecords.Facts facts) {
        if (!facts.lifecycle()) {
            throw notVisible();
        }
    }

    static JsonNode digest(JsonMapper json, long caseId, Object input) {
        var node = json.createObjectNode();
        node.put("case_id", caseId);
        node.set("input", json.valueToTree(input));
        return node;
    }

    static void audit(JsonMapper json, WriteTransaction transaction, String action, long caseId, long actor) {
        var facts = json.createObjectNode();
        facts.put("case_id", caseId);
        facts.put("actor", actor);
        transaction.audit(action, new ResourceRef("case", caseId), new ResourceRef("case", caseId), facts);
    }

    static Instant now(Clock clock) {
        return clock.instant().truncatedTo(ChronoUnit.MICROS);
    }
}
