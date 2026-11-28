package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.casemanagement.application.ManagementCaseChange;
import io.github.iy88.project1.casemanagement.application.ReviewManagerAccess;
import io.github.iy88.project1.casemanagement.application.ReviewNotifications;
import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.notification.application.ReviewNotificationAdapter;
import io.github.iy88.project1.product.application.ProductReviewCaseLifecycle;
import java.time.Instant;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
class ReviewStageConfiguration {
    @Bean
    ProductReviewCaseLifecycle productReviewCaseLifecycle(ReviewCaseStore cases, ApplicationEventPublisher events) {
        return new ProductReviewCaseLifecycle() {
            @Override
            public long open(Instant submittedAt) {
                return cases.open(submittedAt);
            }

            @Override
            public void requireUnclaimed(long caseId) {
                cases.requireUnclaimed(caseId);
            }

            @Override
            public void classificationWithdrawn(long caseId, long applicationId, Instant at) {
                events.publishEvent(new ManagementCaseChange(caseId, "classification_withdrawn",
                        "review:category:" + applicationId, at));
            }

            @Override
            public void withdrawn(long caseId, Instant at) {
                events.publishEvent(new ManagementCaseChange(caseId, "withdrawn", "review:withdrawn", at));
            }
        };
    }

    @Bean
    ReviewActorAccess accountReviewActor(CurrentAccount current) {
        return request -> {
            var identity = current.require(request);
            return new ReviewActorAccess.Actor(identity.account().id(), identity.guard().id(), null,
                    identity.guard().credentialVersion());
        };
    }

    @Bean
    ReviewManagerAccess accountReviewManager(SessionService sessions) {
        return new ReviewManagerAccess() {
            @Override
            public void requireManager(ExecutionContext context, String forbiddenCode, int forbiddenStatus) {
                requireManager(context, forbiddenCode, forbiddenStatus, false);
            }

            @Override
            public void requireManagerForWrite(ExecutionContext context, String forbiddenCode, int forbiddenStatus) {
                requireManager(context, forbiddenCode, forbiddenStatus, true);
            }

            private void requireManager(ExecutionContext context, String code, int status, boolean write) {
                var account = sessions.requireCurrent(Long.parseLong(context.actorId()), context.sessionId(),
                        context.credentialVersion(), write);
                if (!"manager".equals(account.role())) {
                    throw new BusinessError(code, status, "无管理权限");
                }
            }
        };
    }

    @Bean
    NotificationSourcePort reviewNotificationSource(JdbcClient jdbc) {
        return new ReviewNotificationSource(jdbc);
    }

    @Bean
    ReviewNotifications sellerReviewNotifications(ReviewNotificationAdapter notifications) {
        return notifications::reviewDecided;
    }
}
