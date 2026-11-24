package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ExecutionContext;

/** Account-owned check of the current session and management role. */
public interface ReviewManagerAccess {
    /** Current-identity read check; the adapter maps the supplied denial when no role exists. */
    void requireManager(ExecutionContext context, String forbiddenCode, int forbiddenStatus);

    /**
     * Rechecks the current session and management role under the account advisory lock and locks
     * the SessionGuard row before business row locks. Called from {@code WriteExecutor.qualify}.
     */
    void requireManagerForWrite(ExecutionContext context, String forbiddenCode, int forbiddenStatus);
}
