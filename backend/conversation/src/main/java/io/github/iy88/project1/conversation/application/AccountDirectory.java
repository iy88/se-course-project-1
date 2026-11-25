package io.github.iy88.project1.conversation.application;

import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Read-only account projection required by conversations. Qualification checks that need the
 * account lock stay with the account module; this port only exposes current display data.
 */
public interface AccountDirectory {
    Optional<Profile> profile(long accountId);

    boolean writeRestricted(long accountId);

    Map<Long, Profile> profiles(Set<Long> accountIds);

    record Profile(long accountId, String displayName, String avatarUrl) {
        public Profile {
            if (accountId <= 0 || displayName == null || displayName.isBlank()) {
                throw new IllegalArgumentException("Invalid account profile");
            }
        }

        public Profile(long accountId, String displayName) {
            this(accountId, displayName, null);
        }
    }
}
