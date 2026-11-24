package io.github.iy88.project1.product.persistence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class CategoryApplicationTests {
    private static final Instant NOW = Instant.parse("2026-11-24T00:00:00Z");

    @Test
    void recordsExistingCategoryResolution() {
        var application = new CategoryApplication(7, 3, "Calculus", NOW);

        application.approve(9, 12, "existing_category", NOW.plusSeconds(60));

        assertThat(application.status()).isEqualTo("approved");
        assertThat(application.resolution()).isEqualTo("existing_category");
        assertThat(application.resolvedCategoryId()).isEqualTo(12L);
        assertThat(application.decidedByAdminId()).isEqualTo(9L);
    }

    @Test
    void recordsRejectionReasonAndRejectsSecondDecision() {
        var application = new CategoryApplication(7, 3, "Calculus", NOW);
        application.reject(9, "not a category", NOW.plusSeconds(60));

        assertThat(application.status()).isEqualTo("rejected");
        assertThat(application.rejectionReason()).isEqualTo("not a category");
        assertThatThrownBy(() -> application.approve(9, 12, "new_category", NOW.plusSeconds(120)))
                .isInstanceOf(IllegalStateException.class);
    }
}
