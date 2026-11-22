package io.github.iy88.project1.api.account;

import io.github.iy88.project1.account.application.EmailVerificationService;
import io.github.iy88.project1.account.application.EntryTokenService;
import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import java.time.format.DateTimeFormatter;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/account/email-verifications")
@Profile("infrastructure")
class EmailVerificationController {
    private final EmailVerificationService verifications;
    private final EntryTokenService entries;

    EmailVerificationController(EmailVerificationService verifications, EntryTokenService entries) {
        this.verifications = verifications;
        this.entries = entries;
    }

    @PostMapping
    ResponseEntity<VerificationResponse> request(@RequestBody VerificationRequest body,
                                                 HttpServletRequest request) {
        String cookie = AccountCookies.read(request, AccountCookies.ENTRY);
        if (cookie == null) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "账户入口已失效");
        }
        var entry = entries.parse(cookie);
        var result = verifications.request(body.purpose(), body.email(), entry);
        var items = result.requests().stream()
                .map(item -> new Item(Long.toString(item.verificationId()), item.purpose(),
                        DateTimeFormatter.ISO_INSTANT.format(item.expiresAt())))
                .toList();
        return ResponseEntity.status(202)
                .header("Retry-After", Integer.toString(result.retryAfterSeconds()))
                .cacheControl(CacheControl.noStore())
                .body(new VerificationResponse(body.purpose(), items, result.retryAfterSeconds()));
    }

    record VerificationRequest(String purpose, String email) {
    }

    record Item(String verificationId, String purpose, String expiresAt) {
    }

    record VerificationResponse(String purpose, List<Item> requests, int retryAfterSeconds) {
    }
}
