package io.github.iy88.project1.core;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.SQLException;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.cfg.JsonNodeFeature;
import tools.jackson.databind.json.JsonMapper;

@Service
@Profile("infrastructure")
@EnableConfigurationProperties(WriteSettings.class)
public class WriteExecutor {
    private static final JsonMapper CANONICAL_JSON = JsonMapper.builder()
            .enable(JsonNodeFeature.WRITE_PROPERTIES_SORTED, JsonNodeFeature.USE_BIG_DECIMAL_FOR_FLOATS)
            .build();

    private final TransactionTemplate read;
    private final TransactionTemplate write;
    private final JdbcClient jdbc;
    private final WriteRecords records;
    private final WriteSettings settings;

    public WriteExecutor(PlatformTransactionManager manager, JdbcClient jdbc, JsonMapper json, WriteSettings settings) {
        this.jdbc = jdbc;
        this.records = new WriteRecords(jdbc, json);
        this.settings = settings;
        read = template(manager, settings.transactionTimeoutSeconds(), true);
        write = template(manager, settings.transactionTimeoutSeconds(), false);
    }

    public <R, Q> WriteResult<JsonNode> run(ExecutionContext context, String operation, String key, R request,
                                          UseCase<R, Q> useCase) {
        if (TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("A write use case owns its transaction");
        }
        if (!operation.matches("[a-z][a-z0-9_.-]*")) {
            throw new IllegalArgumentException("Invalid operation name");
        }
        if (key == null || key.length() > settings.idempotencyKeyMaxLength() || !key.matches("[!-~]+")) {
            throw new BusinessError("INPUT_INVALID", 422, "Idempotency-Key 无效");
        }
        var digest = digest(useCase.digestInput(request));
        var operationId = UUID.randomUUID();
        var additional = context.actorKind() == ExecutionContext.ActorKind.ACCOUNT
                ? new LockPlan(Map.of(Long.parseLong(context.actorId()), LockPlan.AccountMode.SHARED), Set.of())
                : new LockPlan(Map.of(), Set.of());
        for (int attempt = 0; ; attempt++) {
            try {
                var snapshot = Objects.requireNonNull(read.execute(status -> useCase.prepare(context, request)));
                var plan = snapshot.merge(additional);
                return Objects.requireNonNull(write.execute(status ->
                        execute(context, operation, key, request, useCase, digest, operationId, plan)));
            } catch (LockPlan.Changed changed) {
                additional = additional.merge(changed.additional());
            } catch (RuntimeException failure) {
                if (!retryable(failure)) {
                    throw failure;
                }
            }
            if (attempt == settings.retryLimit()) {
                throw exhausted(operationId);
            }
            try {
                Thread.sleep((long) settings.retryBaseMilliseconds() * (attempt + 1));
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw exhausted(operationId);
            }
        }
    }

    private <R, Q> WriteResult<JsonNode> execute(ExecutionContext context, String operation, String key, R request,
                                               UseCase<R, Q> useCase, byte[] digest, UUID candidate, LockPlan plan) {
        jdbc.sql("SELECT set_config('lock_timeout', ?, true)")
                .param(settings.lockTimeoutSeconds() + "s").query(String.class).single();
        plan.accounts().entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(lock -> {
            String sql = lock.getValue() == LockPlan.AccountMode.EXCLUSIVE
                    ? "SELECT true FROM pg_advisory_xact_lock(?)" : "SELECT true FROM pg_advisory_xact_lock_shared(?)";
            jdbc.sql(sql).param(lock.getKey()).query(Boolean.class).single();
        });
        Q qualifications = useCase.qualify(context, request, plan);
        var claim = records.claim(context, operation, key, candidate, digest, settings.idempotencyRetentionSeconds());
        if (claim.saved().isPresent()) {
            var saved = claim.saved().orElseThrow();
            try {
                useCase.requireReplayAccess(context, qualifications, saved.resource());
                return saved;
            } catch (BusinessError rejected) {
                throw rejected.forOperation(saved.operationId());
            }
        }

        var transaction = new WriteTransaction(context, claim.operationId(), plan, records);
        try {
            var response = useCase.write(transaction, request, qualifications, plan);
            var body = records.complete(claim.operationId(), response);
            return new WriteResult<>(claim.operationId(), response.status(), body, response.resource(), false);
        } catch (BusinessError rejected) {
            throw rejected.forOperation(claim.operationId());
        } finally {
            transaction.close();
        }
    }

    static byte[] digest(JsonNode input) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(CANONICAL_JSON.writeValueAsBytes(input));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static boolean retryable(RuntimeException failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
            if (cause instanceof SQLException sql && ("40001".equals(sql.getSQLState())
                    || "40P01".equals(sql.getSQLState()))) {
                return true;
            }
        }
        return false;
    }

    private static BusinessError exhausted(UUID id) {
        return new BusinessError("TRANSACTION_RETRY_EXHAUSTED", 503, "操作暂时无法完成").forOperation(id);
    }

    private static TransactionTemplate template(PlatformTransactionManager manager, int timeout, boolean readOnly) {
        var transaction = new TransactionTemplate(manager);
        transaction.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        transaction.setTimeout(timeout);
        transaction.setReadOnly(readOnly);
        return transaction;
    }

    public interface UseCase<R, Q> {
        JsonNode digestInput(R request);
        LockPlan prepare(ExecutionContext context, R request);
        Q qualify(ExecutionContext context, R request, LockPlan plan);
        void requireReplayAccess(ExecutionContext context, Q qualifications, ResourceRef resource);
        WriteResult.Response<?> write(WriteTransaction transaction, R request, Q qualifications, LockPlan plan);
    }
}
