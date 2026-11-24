package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.casemanagement.application.ReviewApplication;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

/** Resolves the trusted account context and reports unavailable review dependencies as 503. */
@Component
public class ReviewHttpSupport {
    private final ObjectProvider<ReviewApplication> reviews;
    private final ObjectProvider<ReviewActorAccess> actors;
    private final ApiRequestContext requestContext;

    ReviewHttpSupport(ObjectProvider<ReviewApplication> reviews, ObjectProvider<ReviewActorAccess> actors,
                      ApiRequestContext requestContext) {
        this.reviews = reviews;
        this.actors = actors;
        this.requestContext = requestContext;
    }

    ReviewApplication reviews() {
        var available = reviews.getIfAvailable();
        if (available == null) {
            throw unavailable();
        }
        return available;
    }

    public ExecutionContext context(HttpServletRequest request) {
        var access = actors.getIfAvailable();
        if (access == null) {
            throw unavailable();
        }
        var actor = access.current(request);
        return requestContext.forActor(request, ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(actor.accountId()), actor.sessionId(), actor.originConnectionId(),
                actor.credentialVersion());
    }

    private static BusinessError unavailable() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "审核依赖暂不可用");
    }
}
