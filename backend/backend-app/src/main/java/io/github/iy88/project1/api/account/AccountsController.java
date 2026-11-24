package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.EntryTokenService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/accounts")
@Profile("infrastructure")
class AccountsController {
    private final AccountService accounts;
    private final EntryTokenService entries;

    AccountsController(AccountService accounts, EntryTokenService entries) {
        this.accounts = accounts;
        this.entries = entries;
    }

    @PostMapping
    ResponseEntity<RegisterResponse> register(@RequestBody RegisterRequest body, HttpServletRequest request) {
        var entry = entries.parse(AccountCookies.read(request, AccountCookies.ENTRY));
        long verificationId;
        try {
            verificationId = Long.parseLong(body.verificationId());
        } catch (NumberFormatException invalid) {
            throw new io.github.iy88.project1.core.BusinessError("INPUT_INVALID", 422, "验证码标识无效");
        }
        var account = accounts.register(body.email(), body.displayName(), body.password(), verificationId,
                body.code(), entry);
        return ResponseEntity.status(201)
                .cacheControl(CacheControl.noStore())
                .body(new RegisterResponse(Long.toString(account.id()), account.email(), account.displayName()));
    }

    record RegisterRequest(String email, String displayName, String password, String verificationId, String code) {
    }

    record RegisterResponse(String accountId, String email, String displayName) {
    }
}
