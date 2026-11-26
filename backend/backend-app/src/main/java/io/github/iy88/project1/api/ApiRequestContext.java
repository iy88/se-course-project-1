package io.github.iy88.project1.api;

import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.ExecutionContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class ApiRequestContext extends OncePerRequestFilter {
    private static final String ATTRIBUTE = ApiRequestContext.class.getName() + ".requestId";
    private static final String OPERATION_ATTRIBUTE = ApiRequestContext.class.getName() + ".operationId";
    private final String configVersion;

    public ApiRequestContext(@Value("${project1.config-version}") String configVersion) {
        if (configVersion.isBlank()) {
            throw new IllegalArgumentException("CONFIG_VERSION is required");
        }
        this.configVersion = configVersion;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith(request.getContextPath() + "/api/v1/");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        UUID id = UUID.randomUUID();
        request.setAttribute(ATTRIBUTE, id);
        response.setHeader("X-Request-Id", id.toString());
        var scope = MDC.putCloseable("request_id", id.toString());
        try {
            chain.doFilter(request, response);
        } finally {
            scope.close();
        }
    }

    public static UUID requestId(HttpServletRequest request) {
        return (UUID) request.getAttribute(ATTRIBUTE);
    }

    public ExecutionContext forActor(HttpServletRequest request, ExecutionContext.ActorKind kind, String actorId,
                                     UUID sessionId, UUID originConnectionId, Long credentialVersion) {
        return new ExecutionContext(requestId(request), kind, actorId, sessionId, originConnectionId,
                credentialVersion, configVersion);
    }

    /**
     * Context for a product/category write whose business audit is committed by the domain service.
     * The operation id is the idempotency claim's id, so a replay keeps the original operation id and
     * does not create a second audit.
     */
    public AuditContext forWrite(HttpServletRequest request, ExecutionContext.ActorKind kind, String actorId,
                                 UUID sessionId, UUID originConnectionId, Long credentialVersion) {
        UUID operationId = (UUID) request.getAttribute(OPERATION_ATTRIBUTE);
        if (operationId == null) {
            operationId = UUID.randomUUID();
        }
        return new AuditContext(forActor(request, kind, actorId, sessionId, originConnectionId, credentialVersion),
                operationId);
    }

    /** Called by the idempotency filter before the controller runs. */
    public static void setOperationId(HttpServletRequest request, UUID operationId) {
        request.setAttribute(OPERATION_ATTRIBUTE, operationId);
    }
}
