package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure")
class AccountEmailController {
    private final AccountService accounts;
    private final CurrentAccount current;

    AccountEmailController(AccountService accounts, CurrentAccount current) {
        this.accounts = accounts;
        this.current = current;
    }

    @PutMapping("/api/v1/account/email")
    ResponseEntity<EmailChanged> change(@RequestBody ChangeEmailRequest body, HttpServletRequest request,
                                        HttpServletResponse response) {
        var identity = current.require(request);
        var account = accounts.changeEmail(identity.account(), new AccountService.ChangeEmailCommand(
                body.newEmail(), id(body.oldVerificationId()), body.oldCode(),
                id(body.newVerificationId()), body.newCode()));
        response.addHeader(HttpHeaders.SET_COOKIE, AccountCookies.clear(AccountCookies.SESSION).toString());
        response.addHeader(HttpHeaders.SET_COOKIE, AccountCookies.clear(AccountCookies.CSRF).toString());
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(new EmailChanged(Long.toString(account.id()), account.email()));
    }

    private static long id(String value) {
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

    record ChangeEmailRequest(String newEmail, String oldVerificationId, String oldCode,
                              String newVerificationId, String newCode) {
    }

    record EmailChanged(String accountId, String email) {
    }
}
