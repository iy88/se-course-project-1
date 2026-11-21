package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

/**
 * Read-only lock plan contributed by one or more subjects for one action. Resource callbacks are
 * de-duplicated by {@link LockPlan.Key} across the whole batch and acquired once in the global
 * {@link LockPlan.Key} order. A callback must only lock; it must not mutate subject state.
 */
public final class SubjectPlan {
    private final Map<Long, LockPlan.AccountMode> accounts;
    private final Map<LockPlan.Key, LockAction> resources;

    private SubjectPlan(Map<Long, LockPlan.AccountMode> accounts, Map<LockPlan.Key, LockAction> resources) {
        this.accounts = Map.copyOf(accounts);
        this.resources = Collections.unmodifiableMap(new TreeMap<>(resources));
    }

    public static SubjectPlan empty() {
        return new SubjectPlan(Map.of(), Map.of());
    }

    public static SubjectPlan account(long accountId, LockPlan.AccountMode mode) {
        if (accountId <= 0) {
            throw new IllegalArgumentException("Invalid account lock");
        }
        return new SubjectPlan(Map.of(accountId, Objects.requireNonNull(mode)), Map.of());
    }

    public static SubjectPlan resource(LockPlan.Key key, LockAction action) {
        return new SubjectPlan(Map.of(), Map.of(Objects.requireNonNull(key), Objects.requireNonNull(action)));
    }

    public SubjectPlan merge(SubjectPlan additional) {
        var mergedAccounts = new TreeMap<>(accounts);
        additional.accounts.forEach((id, mode) -> mergedAccounts.merge(id, mode,
                (first, second) -> first == LockPlan.AccountMode.EXCLUSIVE ? first : second));
        var mergedResources = new TreeMap<>(resources);
        additional.resources.forEach(mergedResources::putIfAbsent);
        return new SubjectPlan(mergedAccounts, mergedResources);
    }

    public LockPlan lockPlan() {
        return new LockPlan(accounts, resources.keySet());
    }

    public void acquire(WriteTransaction transaction) {
        Objects.requireNonNull(transaction);
        resources.entrySet().stream()
                .sorted(Map.Entry.comparingByKey())
                .forEach(entry -> {
                    var key = entry.getKey();
                    var action = entry.getValue();
                    transaction.lock(key, () -> action.acquire(transaction));
                });
    }

    /**
     * Returns only the account modes and resource keys that the prepared outer plan does not
     * cover. A non-empty result is propagated as {@link LockPlan.Changed} so the whole write
     * transaction is rolled back and re-planned by the S1 executor.
     */
    public LockPlan missingFrom(LockPlan prepared) {
        var missingAccounts = new TreeMap<Long, LockPlan.AccountMode>();
        accounts.forEach((id, mode) -> {
            var available = prepared.accounts().get(id);
            if (available == null || (mode == LockPlan.AccountMode.EXCLUSIVE
                    && available == LockPlan.AccountMode.SHARED)) {
                missingAccounts.put(id, mode);
            }
        });
        var missingResources = new TreeMap<LockPlan.Key, Boolean>();
        resources.keySet().stream().filter(key -> !prepared.resources().contains(key))
                .forEach(key -> missingResources.put(key, Boolean.TRUE));
        return new LockPlan(missingAccounts, missingResources.keySet());
    }

    @FunctionalInterface
    public interface LockAction {
        void acquire(WriteTransaction transaction);
    }
}
