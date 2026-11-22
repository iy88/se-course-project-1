package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ExecutionContext;

/** Account-owned check of the current session and management role. */
public interface ReviewManagerAccess {
    void requireManager(ExecutionContext context, String forbiddenCode);

    /** Recheck under the account advisory lock and acquire the session guard lock before business row locks. */
    void requireManagerForWrite(ExecutionContext context, String forbiddenCode);
}
