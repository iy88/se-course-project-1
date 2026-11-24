package io.github.iy88.project1.account.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.core.BusinessError;
import org.junit.jupiter.api.Test;

class EntryTokenServiceTests {
    private final EntryTokenService entries = new EntryTokenService(new AccountSettings(
            12, 256, 64, 2_592_000, 604_800, 60, 6, 600, 5, 60, 1_800,
            "0123456789abcdef0123456789abcdef", "s2-v1"));

    @Test
    void issuesAndParsesEntryTokens() {
        var issued = entries.issue();
        var claims = entries.parse(issued.cookie());

        assertThat(claims.nonceDigest()).hasSize(32);
        assertThat(claims.expiresAt().getEpochSecond()).isEqualTo(issued.expiresAt().getEpochSecond());
        assertThat(entries.csrfMatches(claims, issued.csrfToken())).isTrue();
        assertThat(entries.csrfMatches(claims, "other-token")).isFalse();
    }

    @Test
    void rejectsTamperedTokens() {
        var issued = entries.issue();
        String tampered = issued.cookie().substring(0, issued.cookie().length() - 2) + "xx";

        assertThatThrownBy(() -> entries.parse(tampered))
                .isInstanceOf(BusinessError.class)
                .extracting(error -> ((BusinessError) error).code())
                .isEqualTo("AUTHENTICATION_REQUIRED");
    }

    @Test
    void rejectsMissingTokens() {
        assertThatThrownBy(() -> entries.parse(null)).isInstanceOf(BusinessError.class);
        assertThatThrownBy(() -> entries.parse("")).isInstanceOf(BusinessError.class);
    }
}
