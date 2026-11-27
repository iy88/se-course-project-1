package io.github.iy88.project1.api.product;

import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.product.application.ProductCorrectionNotices;
import io.github.iy88.project1.product.application.ProductEditNotices;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DependencyProbeProductNoticesConfigurationTests {
    private final ApplicationContextRunner context = new ApplicationContextRunner()
            .withUserConfiguration(DependencyProbeProductNoticesConfiguration.class);

    @Test
    void dependencyProbeProvidesFailClosedProductNoticePorts() {
        context.withPropertyValues("spring.profiles.active=dependency-probe")
                .run(application -> {
                    assertThat(application).hasSingleBean(ProductEditNotices.class);
                    assertThat(application).hasSingleBean(ProductCorrectionNotices.class);

                    var editNotices = application.getBean(ProductEditNotices.class);
                    var correctionNotices = application.getBean(ProductCorrectionNotices.class);
                    assertThatThrownBy(() -> editNotices.productEdited(context(), 1, 2, 3, "title", true,
                            Instant.EPOCH))
                            .isInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("dependency probing");
                    assertThatThrownBy(() -> correctionNotices.categoryCorrected(context(), 1, 2, 3, 4,
                            "title", Instant.EPOCH))
                            .isInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("dependency probing");
                });
    }

    @Test
    void normalBusinessProfilesDoNotUseDependencyProbeFallbacks() {
        context.withPropertyValues("spring.profiles.active=infrastructure")
                .run(application -> {
                    assertThat(application).doesNotHaveBean(ProductEditNotices.class);
                    assertThat(application).doesNotHaveBean(ProductCorrectionNotices.class);
                });
    }

    private static ExecutionContext context() {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, "1",
                UUID.randomUUID(), null, 1L, "test");
    }
}
