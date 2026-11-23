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
import tools.jackson.databind.JsonNode;

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
    ResponseEntity<ProfileResponse> update(@RequestBody JsonNode body, HttpServletRequest request) {
        var identity = current.require(request);
        boolean hasName = body.has("display_name");
        boolean hasAvatar = body.has("avatar_file_id");
        if (!hasName && !hasAvatar) {
            throw new BusinessError("INPUT_INVALID", 422, "没有可更新的资料");
        }
        String displayName = null;
        if (hasName) {
            JsonNode value = body.get("display_name");
            if (value == null || value.isNull() || !value.isString()) {
                throw new BusinessError("INPUT_INVALID", 422, "显示名称无效");
            }
            displayName = value.asString();
        }
        AccountService.AvatarChange avatar = AccountService.AvatarChange.keep();
        if (hasAvatar) {
            JsonNode value = body.get("avatar_file_id");
            if (value == null || value.isNull()) {
                avatar = AccountService.AvatarChange.remove();
            } else if (!value.isString()) {
                throw new BusinessError("INPUT_INVALID", 422, "头像标识无效");
            } else {
                avatar = AccountService.AvatarChange.replace(avatarId(value.asString()));
            }
        }
        var account = accounts.updateProfile(identity.account(), displayName, avatar);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(new ProfileResponse(Long.toString(account.id()), account.displayName(),
                        avatars.currentUrl(account.id())));
    }

    private static long avatarId(String value) {
        String text = value.trim();
        if (text.isEmpty() || "0".equals(text)) {
            throw new BusinessError("INPUT_INVALID", 422, "头像标识无效");
        }
        try {
            long id = Long.parseLong(text);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new BusinessError("INPUT_INVALID", 422, "头像标识无效");
    }

    record ProfileResponse(String accountId, String displayName, String avatarUrl) {
    }
}
