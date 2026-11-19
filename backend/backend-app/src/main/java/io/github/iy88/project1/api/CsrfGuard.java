package io.github.iy88.project1.api;

import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.net.URI;
import java.util.Collections;
import java.util.Set;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

public class CsrfGuard implements HandlerInterceptor {
    private static final Set<String> SAFE_METHODS = Set.of("GET", "HEAD", "OPTIONS", "TRACE");
    private final Origins origins;
    private final ObjectProvider<Verifier> verifier;

    public CsrfGuard(Origins origins, ObjectProvider<Verifier> verifier) {
        this.origins = origins;
        this.verifier = verifier;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if (!(handler instanceof HandlerMethod) || SAFE_METHODS.contains(request.getMethod())) {
            return true;
        }
        String origin = singleHeader(request, "Origin");
        String token = singleHeader(request, "X-CSRF-Token");
        if (origin == null || !origins.allowedOrigins().contains(origin) || token == null) {
            throw rejected();
        }
        var binding = verifier.getIfAvailable();
        if (binding == null || !binding.matches(request, token)) {
            throw rejected();
        }
        return true;
    }

    private static String singleHeader(HttpServletRequest request, String name) {
        var headers = Collections.list(request.getHeaders(name));
        return headers.size() == 1 && !headers.getFirst().isBlank() ? headers.getFirst() : null;
    }

    private static BusinessError rejected() {
        return new BusinessError("CSRF_INVALID", 403, "请求校验失败");
    }

    @FunctionalInterface
    public interface Verifier {
        boolean matches(HttpServletRequest request, String suppliedToken);
    }

    @ConfigurationProperties("project1.http")
    public record Origins(Set<String> allowedOrigins) {
        public Origins {
            allowedOrigins = allowedOrigins == null ? Set.of() : Set.copyOf(allowedOrigins);
            allowedOrigins.forEach(Origins::validate);
        }

        private static void validate(String value) {
            URI uri = URI.create(value);
            if (!Set.of("https", "http").contains(uri.getScheme() == null ? "" : uri.getScheme())
                    || uri.getHost() == null || uri.getRawUserInfo() != null || !uri.getRawPath().isEmpty()
                    || uri.getRawQuery() != null || uri.getRawFragment() != null || uri.getPort() > 65535
                    || uri.getPort() == 0) {
                throw new IllegalArgumentException("ALLOWED_ORIGINS must contain exact HTTP origins");
            }
        }
    }
}
