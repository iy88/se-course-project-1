package io.github.iy88.project1.api.productreview;

import io.github.iy88.project1.casemanagement.application.ProductReviewPort;
import io.github.iy88.project1.casemanagement.application.ReviewApplication;
import io.github.iy88.project1.casemanagement.application.ReviewManagerAccess;
import io.github.iy88.project1.casemanagement.application.ReviewNotifications;
import io.github.iy88.project1.casemanagement.persistence.ReviewCaseStore;
import io.github.iy88.project1.core.WriteExecutor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import tools.jackson.databind.json.JsonMapper;

/**
 * Stages the review application without requiring the account, product or notification modules to
 * be present. Missing ports are passed as null and the called operation reports 503.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
class ReviewHttpConfiguration {
    @Bean
    ReviewApplication reviewApplication(WriteExecutor writes, ReviewCaseStore cases, JsonMapper json,
                                        ObjectProvider<ProductReviewPort> products,
                                        ObjectProvider<ReviewManagerAccess> managers,
                                        ObjectProvider<ReviewNotifications> notifications) {
        return new ReviewApplication(writes, cases, json, products.getIfAvailable(), managers.getIfAvailable(),
                notifications.getIfAvailable());
    }
}
