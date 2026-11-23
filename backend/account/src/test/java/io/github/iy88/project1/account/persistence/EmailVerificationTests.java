package io.github.iy88.project1.account.persistence;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EmailVerificationTests {
    private static final Instant NOW = Instant.parse("2026-11-23T00:00:00Z");

    private EmailVerification registration(String code) {
        return new EmailVerification("registration", "user@example.com", null,
                new byte[32], UUID.randomUUID(), null, NOW, NOW.plusSeconds(600), code, 6, 2, "s2-v1",
                Map.of(), NOW);
    }

    @Test
    void matchesTheIssuedCode() {
        var verification = registration("123456");

        assertThat(verification.matches("123456")).isTrue();
        assertThat(verification.matches("654321")).isFalse();
        assertThat(verification.matches(null)).isFalse();
    }

    @Test
    void invalidatesAfterTooManyFailures() {
        var verification = registration("123456");

        verification.recordFailure(NOW);
        assertThat(verification.usable(NOW.plusSeconds(1))).isTrue();

        verification.recordFailure(NOW);
        assertThat(verification.usable(NOW.plusSeconds(1))).isFalse();
        assertThat(verification.code()).isNull();
    }

    @Test
    void consumeClearsTheCode() {
        var verification = registration("123456");

        verification.consume(NOW);

        assertThat(verification.consumed()).isTrue();
        assertThat(verification.code()).isNull();
        assertThat(verification.usable(NOW.plusSeconds(1))).isFalse();
    }

    @Test
    void expiresAtTheStoredDeadline() {
        var verification = registration("123456");

        assertThat(verification.usable(NOW.plusSeconds(599))).isTrue();
        assertThat(verification.usable(NOW.plusSeconds(600))).isFalse();
    }
}
