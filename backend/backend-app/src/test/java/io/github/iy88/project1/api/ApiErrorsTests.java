package io.github.iy88.project1.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import io.github.iy88.project1.core.BusinessError;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;

class ApiErrorsTests {
    private final ApiErrors errors = new ApiErrors();
    private final HttpServletRequest request = mock(HttpServletRequest.class);

    @Test
    void rateLimitedExposesTheRetryAfterHeaderFromDetails() {
        var response = errors.business(new BusinessError("RATE_LIMITED", 429, "请求过于频繁，请稍后再试",
                Map.of("retry_after_seconds", 42L)), request);

        assertThat(response.getStatusCode().value()).isEqualTo(429);
        assertThat(response.getHeaders().getFirst(HttpHeaders.RETRY_AFTER)).isEqualTo("42");
        assertThat(response.getBody().error().details())
                .isEqualTo(Map.of("retry_after_seconds", 42L));
    }

    @Test
    void otherErrorsDoNotInventARetryAfterHeader() {
        var response = errors.business(new BusinessError("EMAIL_IN_USE", 409, "该邮箱已被使用"), request);

        assertThat(response.getStatusCode().value()).isEqualTo(409);
        assertThat(response.getHeaders().getFirst(HttpHeaders.RETRY_AFTER)).isNull();
    }
}
