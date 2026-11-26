package io.github.iy88.project1.api.product;

import io.github.iy88.project1.product.application.ProductCorrectionNotices;
import io.github.iy88.project1.product.application.ProductEditNotices;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Keeps the application assembly valid during an infrastructure-only probe.
 *
 * <p>Product business endpoints are not enabled in this profile. If a product notice is invoked
 * unexpectedly, fail closed instead of silently dropping a business notification.
 */
@Configuration(proxyBeanMethods = false)
@Profile("dependency-probe")
class DependencyProbeProductNoticesConfiguration {

    @Bean
    ProductEditNotices dependencyProbeProductEditNotices() {
        return (context, sellerId, productId, editId, productTitle, publiclyVisible, occurredAt) -> {
            throw new IllegalStateException("Product edit notices are unavailable during dependency probing");
        };
    }

    @Bean
    ProductCorrectionNotices dependencyProbeProductCorrectionNotices() {
        return (context, sellerId, productId, editId, caseId, productTitle, occurredAt) -> {
            throw new IllegalStateException("Product correction notices are unavailable during dependency probing");
        };
    }
}
