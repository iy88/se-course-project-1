package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Service
@Profile("infrastructure")
public class TaskWorker {
    private static final Logger LOG = LoggerFactory.getLogger(TaskWorker.class);
    private final TaskSchedules schedules;
    private final WriteExecutor writes;
    private final JsonMapper json;
    private final DeliverySettings settings;
    private final String configVersion;
    private final Map<String, TaskHandler> handlers;

    public TaskWorker(TaskSchedules schedules, WriteExecutor writes, JsonMapper json, DeliverySettings settings,
                      @Value("${project1.config-version}") String configVersion, List<TaskHandler> handlers) {
        this.schedules = schedules;
        this.writes = writes;
        this.json = json;
        this.settings = settings;
        this.configVersion = configVersion;
        this.handlers = handlers.stream().collect(Collectors.toUnmodifiableMap(entry -> entry.kind(), Function.identity()));
    }

    public Set<String> kinds() { return handlers.keySet(); }

    public boolean run(TaskSchedules.Ready ready) {
        var handler = handlers.get(ready.kind());
        if (handler == null) return false;
        var claimed = schedules.claim(ready);
        return claimed.isPresent() ? execute(claimed.orElseThrow(), handler) : schedules.canAcknowledge(ready);
    }

    private boolean execute(TaskSchedules.Lease lease, TaskHandler handler) {
        var task = lease.task();
        var context = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.SYSTEM,
                handler.kind(), null, null, null, configVersion);
        try {
            writes.run(context, "task." + handler.kind(), task.id().toString(), task, useCase(lease, handler));
            return true;
        } catch (RuntimeException failure) {
            String code = failure instanceof BusinessError error && error.code().matches("[A-Z][A-Z0-9_]{0,63}")
                    ? error.code() : "TASK_EXECUTION_FAILED";
            boolean saved = schedules.retry(lease, code);
            if (saved && lease.attempt() >= settings.retryLimit()) {
                LOG.warn("task_id={} result={} attempts={}", task.id(), code, lease.attempt());
            }
            return saved || schedules.canAcknowledge(new TaskSchedules.Ready(task.id(), handler.kind()));
        }
    }

    private WriteExecutor.UseCase<TaskSchedules.Task, Boolean> useCase(TaskSchedules.Lease lease, TaskHandler handler) {
        return new WriteExecutor.UseCase<>() {
            @Override
            public JsonNode digestInput(TaskSchedules.Task task) {
                return json.createObjectNode().put("task_id", task.id().toString());
            }

            @Override
            public LockPlan prepare(ExecutionContext context, TaskSchedules.Task task) {
                return handler.prepare(context, task)
                        .merge(new LockPlan(Map.of(), Set.of(TaskSchedules.key(task.id()))));
            }

            @Override
            public Boolean qualify(ExecutionContext context, TaskSchedules.Task task, LockPlan plan) {
                return Boolean.TRUE;
            }

            @Override
            public void requireReplayAccess(ExecutionContext context, Boolean qualifications, ResourceRef resource) {}

            @Override
            public WriteResult.Response<?> write(WriteTransaction transaction, TaskSchedules.Task task,
                                                  Boolean qualifications, LockPlan plan) {
                handler.lockAndQualify(transaction, task);
                schedules.requireLease(transaction, lease);
                boolean applicable = handler.isApplicable(task);
                if (applicable) handler.execute(transaction, task);
                schedules.finish(transaction, lease, !applicable);
                return new WriteResult.Response<>(204, null, task.spec().source());
            }
        };
    }
}
