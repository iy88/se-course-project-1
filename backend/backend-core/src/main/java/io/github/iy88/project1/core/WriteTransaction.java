package io.github.iy88.project1.core;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.JsonNode;

public final class WriteTransaction {
    private final ExecutionContext context;
    private final UUID operationId;
    private final LockPlan plan;
    private final WriteRecords records;
    private final List<EventIntent> events = new ArrayList<>();
    private final Set<LockPlan.Key> acquired = new HashSet<>();
    private LockPlan.Key last;
    private boolean active = true;

    WriteTransaction(ExecutionContext context, UUID operationId, LockPlan plan, WriteRecords records) {
        this.context = context;
        this.operationId = operationId;
        this.plan = plan;
        this.records = records;
    }

    public ExecutionContext context() { return context; }
    public UUID operationId() { return operationId; }

    public void lock(LockPlan.Key key, Runnable acquire) {
        requirePlanned(key);
        if (last != null && key.compareTo(last) < 0) {
            throw new IllegalStateException("Resource locks must follow the lock plan order");
        }
        acquire.run();
        acquired.add(key);
        last = key;
    }

    /** Requires a resource lock already acquired by this transaction's caller. */
    public void requireLocked(LockPlan.Key key) {
        requirePlanned(key);
        if (!acquired.contains(key)) {
            throw new IllegalStateException("Resource lock has not been acquired");
        }
    }

    /** Requires the exclusive qualification lock acquired by the write executor. */
    public void requireExclusiveAccount(long accountId) {
        requireActive();
        if (plan.accounts().get(accountId) != LockPlan.AccountMode.EXCLUSIVE) {
            throw new LockPlan.Changed(new LockPlan(Map.of(accountId, LockPlan.AccountMode.EXCLUSIVE), Set.of()));
        }
    }

    private void requirePlanned(LockPlan.Key key) {
        requireActive();
        if (!plan.resources().contains(key)) {
            throw new LockPlan.Changed(new LockPlan(Map.of(), Set.of(key)));
        }
    }

    public long audit(String action, ResourceRef target, ResourceRef basis, JsonNode facts) {
        requireActive();
        return records.audit(context, operationId, action, target, basis, facts);
    }

    public EventIntent.Batch addEventIntent(Set<Long> recipients, String eventType, int schemaVersion, ResourceRef source,
                                            String intentKey, ResourceRef payload, Long sourceSequence) {
        requireActive();
        var pending = recipients.stream().sorted()
                .map(recipient -> new EventIntent(UUID.randomUUID(), recipient, eventType, schemaVersion,
                        source, intentKey, payload, sourceSequence))
                .toList();
        events.addAll(pending);
        return new EventIntent.Batch(pending.stream()
                .map(event -> new EventIntent.Item(event.recipientAccountId(), event.eventId())).toList());
    }

    List<EventIntent> events() { return List.copyOf(events); }

    void close() { active = false; }

    private void requireActive() {
        if (!active || !TransactionSynchronizationManager.isActualTransactionActive()
                || TransactionSynchronizationManager.isCurrentTransactionReadOnly()) {
            throw new IllegalStateException("An active write transaction is required");
        }
    }
}
