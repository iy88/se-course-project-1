package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class PasswordHasherTests {
    private final PasswordHasher hasher = new PasswordHasher();

    @Test
    void hashesAndVerifiesPasswords() {
        String hash = hasher.hash("correct horse battery staple");

        assertThat(hash).startsWith("pbkdf2-sha256$");
        assertThat(hasher.matches("correct horse battery staple", hash)).isTrue();
        assertThat(hasher.matches("wrong password", hash)).isFalse();
    }

    @Test
    void producesDifferentSalts() {
        assertThat(hasher.hash("same password")).isNotEqualTo(hasher.hash("same password"));
    }

    @Test
    void hashesTerminalPasswordsInTheSameFormatAsLogin() {
        String password = "管理员登录😃password";

        assertThat(hasher.matches(password, hasher.hash(password.toCharArray()))).isTrue();
    }

    @Test
    void rejectsUnknownHashFormats() {
        assertThat(hasher.matches("password", "plain-text")).isFalse();
        assertThat(hasher.matches("password", "pbkdf2-sha256$1$bad")).isFalse();
    }

    @Test
    void dummyVerificationAlwaysFails() {
        assertThat(hasher.matchesDummy("anything")).isFalse();
    }
}
