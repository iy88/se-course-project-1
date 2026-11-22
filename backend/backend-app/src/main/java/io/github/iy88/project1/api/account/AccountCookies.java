package io.github.iy88.project1.api.account;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Duration;
import java.time.Instant;
import org.springframework.http.ResponseCookie;

final class AccountCookies {
    static final String SESSION = "__Host-se_session";
    static final String CSRF = "__Host-se_csrf";
    static final String ENTRY = "__Host-se_entry";

    private AccountCookies() {
    }

    static String read(HttpServletRequest request, String name) {
        if (request.getCookies() == null) {
            return null;
        }
        for (var cookie : request.getCookies()) {
            if (name.equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
        return null;
    }

    static ResponseCookie cookie(String name, String value, Instant expiresAt) {
        long seconds = Math.max(0, Duration.between(Instant.now(), expiresAt).toSeconds());
        return base(name, value).maxAge(Duration.ofSeconds(seconds)).build();
    }

    static ResponseCookie clear(String name) {
        return base(name, "").maxAge(Duration.ZERO).build();
    }

    private static ResponseCookie.ResponseCookieBuilder base(String name, String value) {
        return ResponseCookie.from(name, value)
                .httpOnly(!CSRF.equals(name))
                .secure(true)
                .sameSite("Lax")
                .path("/");
    }
}
