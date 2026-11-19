package io.github.iy88.project1.core;

import static java.util.Locale.ROOT;

import java.security.MessageDigest;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

final class WriteRecords {
    static final String DIGEST_VERSION = "json-sha256-v1";
    private final JdbcClient jdbc;
    private final JsonMapper json;

    WriteRecords(JdbcClient jdbc, JsonMapper json) {
        this.jdbc = jdbc;
        this.json = json;
    }

    Decision claim(ExecutionContext context, String operation, String key, UUID candidate, byte[] digest, int retention) {
        int inserted = bind(jdbc.sql("""
                INSERT INTO operation_record AS existing
                    (actor_kind, actor_id, operation_name, idempotency_key, digest_version,
                     request_digest, operation_id, expires_at)
                VALUES (:kind, :actor, :operation, :key, :version, :digest, :id,
                        statement_timestamp() + :retention * interval '1 second')
                ON CONFLICT (actor_kind, actor_id, operation_name, idempotency_key)
                DO UPDATE SET digest_version = EXCLUDED.digest_version, request_digest = EXCLUDED.request_digest,
                    operation_id = EXCLUDED.operation_id, expires_at = EXCLUDED.expires_at, response_status = NULL,
                    response_data = NULL, resource_type = NULL, resource_id = NULL
                WHERE existing.expires_at <= statement_timestamp()
                """), context, operation, key)
                .param("version", DIGEST_VERSION).param("digest", digest).param("id", candidate)
                .param("retention", retention).update();
        if (inserted == 1) {
            return new Decision(candidate, Optional.empty());
        }

        return bind(jdbc.sql("""
                SELECT operation_id, digest_version, request_digest, response_status, response_data::text,
                    resource_type, resource_id
                FROM operation_record
                WHERE actor_kind = :kind AND actor_id = :actor AND operation_name = :operation AND idempotency_key = :key
                FOR SHARE
                """), context, operation, key).query((row, index) -> {
            var id = row.getObject("operation_id", UUID.class);
            if (!DIGEST_VERSION.equals(row.getString("digest_version"))
                    || !MessageDigest.isEqual(digest, row.getBytes("request_digest"))) {
                throw new BusinessError("IDEMPOTENCY_PAYLOAD_CONFLICT", 409, "同一幂等键已用于其他输入")
                        .forOperation(id);
            }
            int status = row.getInt("response_status");
            if (row.wasNull()) {
                throw new IllegalStateException("Incomplete operation record");
            }
            String type = row.getString("resource_type");
            var resource = type == null ? null : new ResourceRef(type, row.getLong("resource_id"));
            var body = json.readTree(row.getString("response_data"));
            return new Decision(id, Optional.of(new WriteResult<>(id, status, body, resource, true)));
        }).single();
    }

    JsonNode complete(UUID operationId, WriteResult.Response<?> response) {
        var target = response.resource();
        var body = json.valueToTree(response.data());
        int count = jdbc.sql("""
                UPDATE operation_record SET response_status = :status, response_data = CAST(:data AS jsonb),
                    resource_type = :type, resource_id = :target
                WHERE operation_id = :id
                """).param("status", response.status()).param("data", json.writeValueAsString(body))
                .param("type", target == null ? null : target.type()).param("target", target == null ? null : target.id())
                .param("id", operationId).update();
        if (count != 1) {
            throw new IllegalStateException("Operation reservation is missing");
        }
        return body;
    }

    long audit(ExecutionContext context, UUID operationId, String action, ResourceRef target,
               ResourceRef basis, JsonNode facts) {
        Objects.requireNonNull(target);
        if (action.isBlank() || !facts.isObject()) {
            throw new IllegalArgumentException("Audit requires an action and object facts");
        }
        return jdbc.sql("""
                INSERT INTO audit_record (request_id, operation_id, actor_kind, actor_id, action,
                    target_type, target_id, basis_type, basis_id, facts, config_version)
                VALUES (:request, :operation, :kind, :actor, :action,
                    :type, :target, :basisType, :basisId, CAST(:facts AS jsonb), :config)
                RETURNING audit_id
                """).param("request", context.requestId()).param("operation", operationId)
                .param("kind", context.actorKind().name().toLowerCase(ROOT)).param("actor", context.actorId())
                .param("action", action).param("type", target.type()).param("target", target.id())
                .param("basisType", basis == null ? null : basis.type()).param("basisId", basis == null ? null : basis.id())
                .param("facts", json.writeValueAsString(facts)).param("config", context.configVersion())
                .query(Long.class).single();
    }

    private static JdbcClient.StatementSpec bind(JdbcClient.StatementSpec statement, ExecutionContext context,
                                                String operation, String key) {
        return statement.param("kind", context.actorKind().name().toLowerCase(ROOT)).param("actor", context.actorId())
                .param("operation", operation).param("key", key);
    }

    record Decision(UUID operationId, Optional<WriteResult<JsonNode>> saved) {}
}
