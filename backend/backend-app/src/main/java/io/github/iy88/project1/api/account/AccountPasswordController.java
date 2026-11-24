package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.EntryTokenService;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure")
class AccountPasswordController {
    private final AccountService accounts;
    private final EntryTokenService entries;
    private final CurrentAccount current;

    AccountPasswordController(AccountService accounts, EntryTokenService entries, CurrentAccount current) {
        this.accounts = accounts;
        this.entries = entries;
        this.current = current;
    }

    @PutMapping("/api/v1/account/password")
    ResponseEntity<Void> change(@RequestBody ChangePasswordRequest body, HttpServletRequest request,
                                HttpServletResponse response) {
        var identity = current.require(request);
        accounts.changePassword(identity.account(), body.currentPassword(), body.newPassword());
        response.addHeader(HttpHeaders.SET_COOKIE, AccountCookies.clear(AccountCookies.SESSION).toString());
        response.addHeader(HttpHeaders.SET_COOKIE, AccountCookies.clear(AccountCookies.CSRF).toString());
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @PostMapping("/api/v1/account/password-resets")
    ResponseEntity<Void> reset(@RequestBody ResetPasswordRequest body, HttpServletRequest request) {
        var entry = entries.parse(AccountCookies.read(request, AccountCookies.ENTRY));
        accounts.resetPassword(entry, verificationId(body.verificationId()), body.code(), body.newPassword());
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    private static long verificationId(String value) {
        try {
            long id = Long.parseLong(value);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new BusinessError("INPUT_INVALID", 422, "验证码标识无效");
    }

    record ChangePasswordRequest(String currentPassword, String newPassword) {
    }

    record ResetPasswordRequest(String verificationId, String code, String newPassword) {
    }
}
