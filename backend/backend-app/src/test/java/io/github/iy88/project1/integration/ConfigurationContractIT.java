package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.account.AccountInputRules;
import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.product.ProductSettings;
import java.util.List;
import java.util.function.Supplier;
import org.junit.jupiter.api.Test;

/** Runtime configuration boundaries used by the production application wiring. */
class ConfigurationContractIT {
    private static final String KEY = "0123456789abcdef0123456789abcdef";

    @Test
    void accountSettingsAcceptProductionBoundsAndRejectEveryUnsafeDurationOrCodeRule() {
        assertThat(account(60, 60, 30, 6, 600, 5, 30, 1800, KEY, "v1").inputRules())
                .isEqualTo(new AccountInputRules(8, 1024, 64));

        List<Supplier<AccountSettings>> invalid = List.of(
                () -> account(0, 60, 30, 6, 600, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 0, 30, 6, 600, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 61, 30, 6, 600, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 0, 6, 600, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 60, 6, 600, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 5, 60, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 11, 60, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 59, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 1801, 5, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 600, 0, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 600, 21, 30, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 600, 5, 0, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 600, 5, 601, 1800, KEY, "v1"),
                () -> account(60, 60, 30, 6, 600, 5, 30, 600, KEY, "v1"),
                () -> account(60, 60, 30, 6, 600, 5, 30, 1800, null, "v1"),
                () -> account(60, 60, 30, 6, 600, 5, 30, 1800, "short", "v1"),
                () -> account(60, 60, 30, 6, 600, 5, 30, 1800, KEY, null),
                () -> account(60, 60, 30, 6, 600, 5, 30, 1800, KEY, " "));
        for (int index = 0; index < invalid.size(); index++) {
            Supplier<AccountSettings> factory = invalid.get(index);
            try {
                factory.get();
                throw new AssertionError("account settings case " + index + " was accepted");
            } catch (IllegalArgumentException expected) {
                // Expected boundary rejection.
            }
        }
    }

    @Test
    void productSettingsCoverTheCompleteValidationMatrix() {
        assertThat(product(100, 5000, 1_000_000, 20, 100, 9, 500, 10, 60).pageSizeMax())
                .isEqualTo(100);
        assertInvalidProduct(0, 5000, 100, 20, 100, 9, 500, 10, 60);
        assertInvalidProduct(501, 5000, 100, 20, 100, 9, 500, 10, 60);
        assertInvalidProduct(100, 0, 100, 20, 100, 9, 500, 10, 60);
        assertInvalidProduct(100, 50001, 100, 20, 100, 9, 500, 10, 60);
        assertInvalidProduct(100, 5000, 0, 20, 100, 9, 500, 10, 60);
        assertInvalidProduct(100, 5000, 100, 0, 100, 9, 500, 10, 60);
        assertInvalidProduct(100, 5000, 100, 101, 100, 9, 500, 10, 60);
        assertInvalidProduct(100, 5000, 100, 20, 1001, 9, 500, 10, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, -1, 500, 10, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, 51, 500, 10, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, 9, 0, 10, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, 9, 5001, 10, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, 9, 500, 0, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, 9, 500, 1001, 60);
        assertInvalidProduct(100, 5000, 100, 20, 100, 9, 500, 10, 0);
        assertInvalidProduct(100, 5000, 100, 20, 100, 9, 500, 10, 86401);
    }

    @Test
    void accountInputRulesUseCodePointLengthsAndTrimDisplayNames() {
        var rules = new AccountInputRules(8, 12, 3);
        assertThat(rules.displayName(" 用户 ")).isEqualTo("用户");
        rules.requirePassword("密码密码密码密码");
        assertThatThrownBy(() -> rules.requirePassword(null)).hasMessage("密码长度不符合要求");
        assertThatThrownBy(() -> rules.requirePassword("short")).hasMessage("密码长度不符合要求");
        assertThatThrownBy(() -> rules.displayName("four")).hasMessage("显示名称无效");
        assertThatThrownBy(() -> new AccountInputRules(7, 12, 3)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new AccountInputRules(8, 1025, 3)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new AccountInputRules(8, 12, 0)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new AccountInputRules(8, 12, 257)).isInstanceOf(IllegalArgumentException.class);
    }

    private static AccountSettings account(int absolute, int idle, int renew, int codeLength, int ttl,
                                           int attempts, int resend, int entryTtl, String key, String version) {
        return new AccountSettings(8, 1024, 64, absolute, idle, renew, codeLength, ttl, attempts, resend,
                entryTtl, key, version);
    }

    private static ProductSettings product(int title, int description, long price, int pageSize, int pageMax,
                                           int images, int commentLength, int rateCount, int rateWindow) {
        return new ProductSettings(title, description, price, pageSize, pageMax, images,
                commentLength, rateCount, rateWindow);
    }

    private static void assertInvalidProduct(int title, int description, long price, int pageSize, int pageMax,
                                             int images, int commentLength, int rateCount, int rateWindow) {
        assertThatThrownBy(() -> product(title, description, price, pageSize, pageMax, images,
                commentLength, rateCount, rateWindow)).isInstanceOf(IllegalArgumentException.class);
    }
}
