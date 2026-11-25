package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.account.application.EntryTokenService;
import java.time.format.DateTimeFormatter;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/account/entry-context")
@Profile("infrastructure")
class AccountEntryController {
    private final EntryTokenService entries;
    private final AccountSettings settings;

    AccountEntryController(EntryTokenService entries, AccountSettings settings) {
        this.entries = entries;
        this.settings = settings;
    }

    @GetMapping
    ResponseEntity<EntryContextResponse> context() {
        var issued = entries.issue();
        var body = new EntryContextResponse(issued.csrfToken(),
                DateTimeFormatter.ISO_INSTANT.format(issued.expiresAt()),
                new Limits(settings.emailCodeLength(), settings.emailCodeTtlSeconds(),
                        settings.emailResendIntervalSeconds(), settings.passwordMinLength(),
                        settings.passwordMaxLength(), settings.displayNameMaxLength()));
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE,
                        AccountCookies.cookie(AccountCookies.ENTRY, issued.cookie(), issued.expiresAt()).toString())
                .cacheControl(CacheControl.noStore())
                .body(body);
    }

    record EntryContextResponse(String csrfToken, String expiresAt, Limits limits) {
    }

    record Limits(int emailCodeLength, int codeTtlSeconds, int resendIntervalSeconds, int passwordMinLength,
                  int passwordMaxLength, int displayNameMaxLength) {
    }
}
