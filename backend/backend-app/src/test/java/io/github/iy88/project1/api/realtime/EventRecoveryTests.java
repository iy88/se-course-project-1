package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.api.ApiErrors;
import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.messaging.EventReplay;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class EventRecoveryTests {
    private final EventReplay events = mock(EventReplay.class);
    private final RealtimeAccess access = mock(RealtimeAccess.class);
    private final RealtimeSettings settings = new RealtimeSettings(100, 5, 8, 4, 5, 20, 60, 16384, 500);
    private final org.springframework.test.web.servlet.MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new EventRecoveryController(events, access, settings))
                    .setControllerAdvice(new ApiErrors()).addFilters(new ApiRequestContext("test")).build();

    @Test
    void rejectsUnauthenticatedHeadBeforeReadingStorage() throws Exception {
        when(access.authenticate(any())).thenThrow(new BusinessError("AUTHENTICATION_REQUIRED", 401, "请登录"));

        mvc.perform(get("/api/v1/account/events/head"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTHENTICATION_REQUIRED"))
                .andExpect(jsonPath("$.request_id").isString());
        verifyNoInteractions(events);
    }

    @Test
    void usesAuthenticatedAccountAndSerializesHiddenEventsAsCursorAdvance() throws Exception {
        UUID epoch = UUID.randomUUID();
        when(access.authenticate(any())).thenReturn(new RealtimeAccess.Session(14, UUID.randomUUID(), 1L, "test"));
        when(events.replay(any(), eq(epoch), eq(0L), eq(100), eq(access))).thenAnswer(call -> {
            io.github.iy88.project1.core.ExecutionContext context = call.getArgument(0);
            org.assertj.core.api.Assertions.assertThat(context.actorId()).isEqualTo("14");
            return new EventReplay.Page(List.of(new EventReplay.CursorAdvance(epoch, 1, 2)), 2, 2, false);
        });

        mvc.perform(get("/api/v1/account/events").param("epoch", epoch.toString()).param("after_seq", "0")
                        .param("recipient_account_id", "99"))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.items[0].type").value("cursor_advance"))
                .andExpect(jsonPath("$.items[0].through_seq").value(2))
                .andExpect(jsonPath("$.items[0].data").doesNotExist())
                .andExpect(jsonPath("$.next_cursor.after_seq").value(2));
    }
}
