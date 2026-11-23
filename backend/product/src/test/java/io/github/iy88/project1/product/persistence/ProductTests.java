package io.github.iy88.project1.product.persistence;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class ProductTests {
    private static final Instant NOW = Instant.parse("2026-11-23T00:00:00Z");

    @Test
    void startsPendingReviewAtVersionOne() {
        var product = new Product(7, "Calculus", "Used book", 1_200, NOW);

        assertThat(product.lifecycleState()).isEqualTo(Product.PENDING_REVIEW);
        assertThat(product.contentVersion()).isEqualTo(1);
        assertThat(product.occupiedByTradeId()).isNull();
        assertThat(product.deleted()).isFalse();
    }

    @Test
    void editingContentAdvancesTheVersion() {
        var product = new Product(7, "Calculus", "Used book", 1_200, NOW);

        product.editContent("Calculus 2nd", "Updated", 1_000, NOW.plusSeconds(60));

        assertThat(product.title()).isEqualTo("Calculus 2nd");
        assertThat(product.description()).isEqualTo("Updated");
        assertThat(product.priceCents()).isEqualTo(1_000);
        assertThat(product.contentVersion()).isEqualTo(2);
        assertThat(product.updatedAt()).isEqualTo(NOW.plusSeconds(60));
    }

    @Test
    void transitionsKeepTheContentVersion() {
        var product = new Product(7, "Calculus", "Used book", 1_200, NOW);

        product.transition(Product.PUBLIC, NOW.plusSeconds(30));
        assertThat(product.lifecycleState()).isEqualTo(Product.PUBLIC);
        assertThat(product.contentVersion()).isEqualTo(1);

        product.transition(Product.OFF_SHELF, NOW.plusSeconds(60));
        assertThat(product.lifecycleState()).isEqualTo(Product.OFF_SHELF);
        assertThat(product.contentVersion()).isEqualTo(1);
    }
}
