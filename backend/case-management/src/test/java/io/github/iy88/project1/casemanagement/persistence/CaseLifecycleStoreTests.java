package io.github.iy88.project1.casemanagement.persistence;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

/** Decoding of the JSONB affected-scope projection. */
class CaseLifecycleStoreTests {
    @Test
    void decodesCanonicalAndCompactJsonbScopes() {
        String canonical = "[{\"resource_id\": \"21\", \"resource_type\": \"account\"},"
                + " {\"resource_id\": \"22\", \"resource_type\": \"account\"},"
                + " {\"resource_id\": \"24\", \"resource_type\": \"product\"}]";
        String compact = "[{\"resource_type\":\"account\",\"resource_id\":\"23\"}]";

        assertThat(CaseLifecycleStore.affectedAccounts(canonical)).containsExactly(21L, 22L);
        assertThat(CaseLifecycleStore.affectedAccounts(compact)).containsExactly(23L);
    }
}
