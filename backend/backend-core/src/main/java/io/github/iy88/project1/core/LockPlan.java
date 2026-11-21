package io.github.iy88.project1.core;

import java.io.Serial;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

public record LockPlan(Map<Long, AccountMode> accounts, Set<Key> resources) {
    public LockPlan {
        accounts = Map.copyOf(accounts);
        resources = Set.copyOf(resources);
        if (accounts.keySet().stream().anyMatch(id -> id <= 0)) {
            throw new IllegalArgumentException("Account lock IDs must be positive");
        }
    }

    public LockPlan merge(LockPlan additional) {
        var mergedAccounts = new TreeMap<>(accounts);
        additional.accounts.forEach((id, mode) -> mergedAccounts.merge(id, mode,
                (first, second) -> first == AccountMode.EXCLUSIVE ? first : second));
        var mergedResources = new TreeSet<>(resources);
        mergedResources.addAll(additional.resources);
        return new LockPlan(mergedAccounts, mergedResources);
    }

    public enum AccountMode { SHARED, EXCLUSIVE }

    public enum Domain {
        ACCOUNT_PROFILE, EMAIL_VERIFICATION, PRODUCT, PRODUCT_DETAIL, CATEGORY, TRADE, TRADE_DETAIL, CASE,
        CHAT_CONVERSATION, TRADE_CONVERSATION, CASE_CONVERSATION, MESSAGE, READ_PROGRESS,
        FILE_RECORD, FILE_REFERENCE, NOTIFICATION, TASK, USER_EVENT_SEQUENCE
    }

    public record Key(Domain domain, List<Long> parts) implements Comparable<Key> {
        public Key {
            java.util.Objects.requireNonNull(domain);
            parts = List.copyOf(parts);
            if (parts.isEmpty() || parts.stream().anyMatch(part -> part < 0)) {
                throw new IllegalArgumentException("Invalid resource lock key");
            }
        }

        @Override
        public int compareTo(Key other) {
            int order = domain.compareTo(other.domain);
            if (order != 0) {
                return order;
            }
            for (int index = 0; index < Math.min(parts.size(), other.parts.size()); index++) {
                order = Long.compare(parts.get(index), other.parts.get(index));
                if (order != 0) {
                    return order;
                }
            }
            return Integer.compare(parts.size(), other.parts.size());
        }
    }

    public static final class Changed extends RuntimeException {
        @Serial
        private static final long serialVersionUID = 1L;
        private final transient LockPlan additional;

        public Changed(LockPlan additional) {
            this.additional = java.util.Objects.requireNonNull(additional);
        }

        public LockPlan additional() { return additional; }
    }
}
