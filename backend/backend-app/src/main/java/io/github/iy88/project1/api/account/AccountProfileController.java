package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/account/profile")
@Profile("infrastructure")
class AccountProfileController {
    private final AccountService accounts;
    private final io.github.iy88.project1.account.application.AccountAvatarService avatars;
    private final CurrentAccount current;

    AccountProfileController(AccountService accounts,
                             io.github.iy88.project1.account.application.AccountAvatarService avatars,
                             CurrentAccount current) {
        this.accounts = accounts;
        this.avatars = avatars;
        this.current = current;
    }

    @PatchMapping
    ResponseEntity<ProfileResponse> update(@RequestBody ProfileRequest body, HttpServletRequest request) {
        var identity = current.require(request);
        var account = accounts.updateProfile(identity.account(), body.displayName(), body.avatarFileId());
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(new ProfileResponse(Long.toString(account.id()), account.displayName(),
                        avatars.currentUrl(account.id())));
    }

    record ProfileRequest(String displayName, String avatarFileId) {
    }

    record ProfileResponse(String accountId, String displayName, String avatarUrl) {
    }
}
