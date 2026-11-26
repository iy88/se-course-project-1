package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.casemanagement.application.CaseApplication;
import io.github.iy88.project1.casemanagement.application.CaseQueries;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

/**
 * Resolves the trusted account context and reports unavailable case dependencies as 503. The
 * component exists for every web profile; identity and business beans stay optional so lightweight
 * controller slices can load without the infrastructure profile.
 */
@Component
public class CaseHttpSupport {
    private final ObjectProvider<CaseApplication> applications;
    private final ObjectProvider<CaseQueries> queries;
    private final ObjectProvider<CurrentAccount> current;
    private final ApiRequestContext requests;

    CaseHttpSupport(ObjectProvider<CaseApplication> applications, ObjectProvider<CaseQueries> queries,
                    ObjectProvider<CurrentAccount> current, ApiRequestContext requests) {
        this.applications = applications;
        this.queries = queries;
        this.current = current;
        this.requests = requests;
    }

    CaseApplication application() {
        var available = applications.getIfAvailable();
        if (available == null) {
            throw unavailable();
        }
        return available;
    }

    CaseQueries queries() {
        var available = queries.getIfAvailable();
        if (available == null) {
            throw unavailable();
        }
        return available;
    }

    ExecutionContext context(HttpServletRequest request) {
        var accounts = current.getIfAvailable();
        if (accounts == null) {
            throw unavailable();
        }
        var actor = accounts.require(request);
        return requests.forActor(request, ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(actor.account().id()), actor.guard().id(), null,
                (long) actor.guard().credentialVersion());
    }

    static BusinessError unavailable() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "事项服务暂不可用");
    }
}
