package io.github.iy88.project1.category.persistence;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class CategoryNameTests {
    private static final Instant NOW = Instant.parse("2026-11-23T00:00:00Z");

    @Test
    void mainNamesBecomeAliasesOnRename() {
        var name = new CategoryName(3, "Books", "main", NOW);

        name.toAlias();

        assertThat(name.nameKind()).isEqualTo("alias");
        assertThat(name.active()).isTrue();
    }

    @Test
    void deactivationIsIdempotent() {
        var name = new CategoryName(3, "Textbooks", "alias", NOW);

        name.deactivate(NOW.plusSeconds(10));
        name.deactivate(NOW.plusSeconds(20));

        assertThat(name.active()).isFalse();
    }
}
