package io.github.iy88.project1.core;

import static java.util.Locale.ROOT;

import java.util.Map;
import java.util.Objects;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.json.JsonMapper;

/**
 * Reusable business-audit port for use cases that own a Spring transaction directly instead of
 * going through {@link WriteExecutor}.
 *
 * <p>The port refuses to run without an active read-write transaction. It therefore cannot be used
 * to append an audit after the business commit, and a failed insert propagates to the caller so the
 * owning transaction rolls the business change back. Callers must pass the actual request actor and
 * operation id; the idempotency filter never provides facts supplied by the client.
 */
@Service
@Profile("infrastructure")
public class AuditStore {
    private final JdbcClient jdbc;
    private final JsonMapper json;

    public AuditStore(JdbcClient jdbc, JsonMapper json) {
        this.jdbc = jdbc;
        this.json = json;
    }

    public long record(AuditContext context, String action, ResourceRef target, ResourceRef basis,
                       Map<String, ?> facts) {
        Objects.requireNonNull(context);
        Objects.requireNonNull(target);
        if (action == null || action.isBlank()) {
            throw new IllegalArgumentException("Audit requires a named action");
        }
        if (!TransactionSynchronizationManager.isActualTransactionActive()
                || TransactionSynchronizationManager.isCurrentTransactionReadOnly()) {
            throw new IllegalStateException("Business audit requires an active write transaction");
        }
        var execution = context.execution();
        Map<String, ?> auditFacts = facts == null ? Map.of() : facts;
        return jdbc.sql("""
                        INSERT INTO audit_record (request_id, operation_id, actor_kind, actor_id, action,
                            target_type, target_id, basis_type, basis_id, facts, config_version)
                        VALUES (:request, :operation, :kind, :actor, :action,
                            :type, :target, :basisType, :basisId, CAST(:facts AS jsonb), :config)
                        RETURNING audit_id
                        """)
                .param("request", execution.requestId())
                .param("operation", context.operationId())
                .param("kind", execution.actorKind().name().toLowerCase(ROOT))
                .param("actor", execution.actorId())
                .param("action", action)
                .param("type", target.type())
                .param("target", target.id())
                .param("basisType", basis == null ? null : basis.type())
                .param("basisId", basis == null ? null : basis.id())
                .param("facts", json.writeValueAsString(auditFacts))
                .param("config", execution.configVersion())
                .query(Long.class)
                .single();
    }
}
