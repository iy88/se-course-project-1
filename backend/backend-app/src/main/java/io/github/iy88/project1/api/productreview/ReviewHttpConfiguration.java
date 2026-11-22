package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.casemanagement.application.ProductReviewPort;
import io.github.iy88.project1.casemanagement.application.ReviewApplication;
import io.github.iy88.project1.casemanagement.application.ReviewManagerAccess;
import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.notification.application.ReviewNotificationAdapter;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import tools.jackson.databind.json.JsonMapper;

/** Wires review decisions to the notification adapter in the shared write transaction. */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
class ReviewHttpConfiguration {
    @Bean
    ReviewApplication reviewApplication(WriteExecutor writes, ReviewCaseStore cases, JsonMapper json,
                                        ObjectProvider<ProductReviewPort> products,
                                        ObjectProvider<ReviewManagerAccess> managers,
                                        ReviewNotificationAdapter notifications) {
        return new ReviewApplication(writes, cases, json, products.getIfAvailable(), managers.getIfAvailable(),
                notifications::reviewDecided);
    }
}
