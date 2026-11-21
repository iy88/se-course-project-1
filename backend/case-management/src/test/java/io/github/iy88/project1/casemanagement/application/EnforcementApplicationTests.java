package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.storage.persistence.FileReferences;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

class EnforcementApplicationTests {
    private static final ExecutionContext CONTEXT = new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, "7", UUID.randomUUID(), null, 1L, "test");
    private static final EnforcementCommand COMMAND = new EnforcementCommand(3, List.of(
            EnforcementInstruction.of("e1", EnforcementAction.WITHDRAW_PUBLIC_ACCESS,
                    new ResourceRef("product", 5))), List.of(1L), List.of(), "reason", Instant.parse("2026-01-01T00:00:00Z"));

    private final CaseEnforcementPort cases = mock(CaseEnforcementPort.class);
    private final EnforcementApplication application = new EnforcementApplication(
            mock(WriteExecutor.class), cases, mock(AccountEnforcementPort.class),
            mock(ProductEnforcementPort.class), mock(TradeEnforcementPort.class),
            mock(ConversationEnforcementPort.class), mock(EnforcementNotifications.class),
            mock(FileReferences.class), JsonMapper.builder().build());

    @Test
    void recordsOnlyGenuineFailedBusinessExecutionInTheCaseFailureTrail() {
        application.recordFailure(CONTEXT, COMMAND, new BusinessError("TARGET_STATE_CONFLICT", 409, "conflict"));

        verify(cases).recordFailure(CONTEXT, COMMAND, "TARGET_STATE_CONFLICT", "conflict");
    }

    @Test
    void neverRecordsReplayAuthorizationOrConflictFailuresAsExecutionFailures() {
        application.recordFailure(CONTEXT, COMMAND,
                new BusinessError("IDEMPOTENCY_PAYLOAD_CONFLICT", 409, "payload"));
        application.recordFailure(CONTEXT, COMMAND, new BusinessError("NOT_CASE_MANAGER", 404, "auth"));
        application.recordFailure(CONTEXT, COMMAND, new BusinessError("STATE_CONFLICT", 409, "state"));

        verify(cases, never()).recordFailure(any(), any(), anyString(), anyString());
    }
}
