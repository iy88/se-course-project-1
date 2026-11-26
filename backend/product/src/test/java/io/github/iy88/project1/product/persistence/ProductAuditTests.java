package io.github.iy88.project1.product.persistence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ProductAuditTests {
    private static final Instant NOW = Instant.parse("2026-11-24T00:00:00Z");

    @Test
    void savesDecisionFactsAndReadsTheReviewedVersion() {
        var audit = new ProductAudit(7, 1, 41, NOW);

        audit.decide(9, true, null,
                Map.of("content_version", 3, "title", "Calculus", "image_file_ids", List.of(11L, 12L)),
                Map.of("status", "approved"), List.of(4L, 5L), NOW.plusSeconds(60));

        assertThat(audit.status()).isEqualTo("passed");
        assertThat(audit.decidedByAdminId()).isEqualTo(9L);
        assertThat(audit.decidedAt()).isEqualTo(NOW.plusSeconds(60));
        assertThat(audit.reviewedContentVersion()).isEqualTo(3);
        assertThat(audit.reviewedContent()).containsEntry("title", "Calculus");
        assertThat(audit.reviewedBannedItemIds()).containsExactly(4L, 5L);
    }

    @Test
    void keepsReviewedVersionEmptyBeforeDecision() {
        var audit = new ProductAudit(7, 1, 41, NOW);

        assertThat(audit.reviewedContentVersion()).isNull();
        assertThat(audit.decidedByAdminId()).isNull();
    }

    @Test
    void rejectsASecondDecisionAndKeepsAWithdrawnAuditWithdrawn() {
        var audit = new ProductAudit(7, 1, 41, NOW);
        audit.decide(9, false, "missing category", Map.of("content_version", 1), null, List.of(),
                NOW.plusSeconds(60));

        assertThatThrownBy(() -> audit.decide(10, true, null, Map.of("content_version", 2), null, List.of(),
                NOW.plusSeconds(120))).isInstanceOf(IllegalStateException.class);

        audit.withdraw(NOW.plusSeconds(180));
        assertThat(audit.status()).isEqualTo("rejected");
        assertThat(audit.withdrawnAt()).isNull();
    }
}
