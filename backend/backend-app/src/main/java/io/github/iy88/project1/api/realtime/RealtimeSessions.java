package io.github.iy88.project1.api.realtime;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Optional;

/** Account-owned cookie, current Session and Session-bound CSRF checks. */
public interface RealtimeSessions {
    /** An empty result denotes a request without a Session cookie. */
    Optional<RealtimeAccess.Session> resolve(HttpServletRequest request);

    void requireCurrent(RealtimeAccess.Session session);

    void requireCsrf(RealtimeAccess.Session session, String token);

    PublicAccountLimits publicLimits();

    record PublicAccountLimits(int passwordMinLength, int passwordMaxLength, int displayNameMaxLength) {}
}
