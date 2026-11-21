package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.api.ApiErrors;
import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.core.BusinessError;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class CapabilitiesControllerTests {
    private final RealtimeSessions sessions = mock(RealtimeSessions.class);
    private final RealtimeAccess.Session session = new RealtimeAccess.Session(14, UUID.randomUUID(), 1L, "test");
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(
                    new CapabilitiesController(sessions, "test-v1"))
            .setControllerAdvice(new ApiErrors()).addFilters(new ApiRequestContext("test-v1")).build();

    @Test
    void guestsReceiveConfigVersionAndPublicAccountLimitsWithoutBusinessCapabilities() throws Exception {
        when(sessions.resolve(any())).thenReturn(Optional.empty());
        when(sessions.publicLimits()).thenReturn(new RealtimeSessions.PublicAccountLimits(12, 256, 64));

        mvc.perform(get("/api/v1/capabilities"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.config_version").value("test-v1"))
                .andExpect(jsonPath("$.enabled_capabilities").doesNotExist())
                .andExpect(jsonPath("$.limits.password_min_length").value(12))
                .andExpect(jsonPath("$.limits.display_name_max_length").value(64))
                .andExpect(jsonPath("$.limits.password_max_length").value(256))
                .andExpect(jsonPath("$.limits.length()").value(3));
    }

    @Test
    void aCurrentSessionReceivesTheSamePublicConfiguration() throws Exception {
        when(sessions.resolve(any())).thenReturn(Optional.of(session));
        when(sessions.publicLimits()).thenReturn(new RealtimeSessions.PublicAccountLimits(12, 256, 64));

        mvc.perform(get("/api/v1/capabilities"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.config_version").value("test-v1"))
                .andExpect(jsonPath("$.enabled_capabilities").doesNotExist())
                .andExpect(jsonPath("$.limits.password_min_length").value(12));

        verify(sessions).requireCurrent(session);
    }

    @Test
    void anExpiredCookieIsHandledByTheIdentityContract() throws Exception {
        when(sessions.resolve(any())).thenThrow(new BusinessError("AUTHENTICATION_REQUIRED", 401, "请登录"));

        mvc.perform(get("/api/v1/capabilities"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTHENTICATION_REQUIRED"));
    }
}
