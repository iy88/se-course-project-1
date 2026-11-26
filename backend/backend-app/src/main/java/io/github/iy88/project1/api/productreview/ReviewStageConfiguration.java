package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.casemanagement.application.ManagementCaseChange;
import io.github.iy88.project1.casemanagement.application.ReviewManagerAccess;
import io.github.iy88.project1.casemanagement.application.ReviewNotifications;
import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import io.github.iy88.project1.notification.application.ReviewNotificationAdapter;
import io.github.iy88.project1.product.application.ProductReviewCaseLifecycle;
import java.time.Instant;
import java.util.Optional;
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
            public void contentUpdated(long caseId, long editId, Instant at) {
                events.publishEvent(new ManagementCaseChange(caseId, "review_updated", "review:edit:" + editId, at));
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
        return (context, facts) -> {
            if (!ReviewNotificationAdapter.SOURCE_TYPE.equals(facts.source().type())) {
                return Optional.empty();
            }
            return jdbc.sql("""
                            SELECT p.product_id, a.status, a.decision_reason,
                                   COALESCE(a.reviewed_content ->> 'title', p.title) AS title
                            FROM product_audit a JOIN product p ON p.product_id = a.product_id
                            WHERE a.audit_id = ? AND p.seller_account_id = ?
                              AND p.deleted_at IS NULL AND a.status IN ('passed', 'rejected')
                            """)
                    .param(facts.source().id()).param(Long.parseLong(context.actorId()))
                    .query((row, index) -> {
                        var reason = row.getString("decision_reason");
                        boolean passed = "passed".equals(row.getString("status"));
                        var summary = passed ? "商品审核通过" : "商品审核未通过";
                        var body = passed ? "该商品已通过审核。你可以前往商品详情查看当前展示状态。"
                                : "你可以根据审核意见修改商品内容，再提交审核。";
                        if (!passed && reason != null && !reason.isBlank()) {
                            body = "审核意见\n" + reason + "\n\n" + body;
                        }
                        return new NotificationSourcePort.NotificationSourceView(summary,
                                new ResourceRef("product", row.getLong("product_id")), row.getString("title"), body);
                    }).optional();
        };
    }

    @Bean
    ReviewNotifications sellerReviewNotifications(ReviewNotificationAdapter notifications) {
        return notifications::reviewDecided;
    }
}
