package io.github.iy88.project1.api.notification;

import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.notification.application.NotificationPage;
import io.github.iy88.project1.notification.application.NotificationQueries;
import io.github.iy88.project1.notification.application.NotificationView;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import tools.jackson.databind.json.JsonMapper;

/**
 * HTTP contract of the notification endpoints.
 *
 * The real controller, wire format and error advice run here; the notification
 * queries, the read command and the session adapter are stand-ins, so the test
 * needs neither a database nor the identity module.
 */
@SpringBootTest(properties = {
        "spring.autoconfigure.exclude=org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration,"
                + "org.springframework.boot.data.redis.autoconfigure.DataRedisAutoConfiguration",
        "project1.http.allowed-origins=http://127.0.0.1:3000"})
@AutoConfigureMockMvc
class NotificationControllerTests {
    private static final Instant OCCURRED = Instant.parse("2026-11-20T08:55:00Z");
    private static final Instant READ_AT = Instant.parse("2026-11-20T09:00:00Z");
    private static final long ACCOUNT = 7L;
    private static final String ANONYMOUS_HEADER = "X-Test-Anonymous";
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String CSRF_TOKEN = "test-csrf";

    @Autowired
    private MockMvc mvc;

    @TestConfiguration
    static class Stubs {
        @Bean
        @Primary
        NotificationQueries stubNotificationQueries() {
            var queries = mock(NotificationQueries.class);
            when(queries.list(any(), any())).thenReturn(new NotificationPage(
                    List.of(new NotificationView(11L, "product_audit.passed", OCCURRED, null,
                            "商品《高等数学》已通过审核", new ResourceRef("product", 42L))),
                    2, 20, 21, 3));
            when(queries.get(any(), eq(11L))).thenReturn(new NotificationView(11L, "product_audit.passed",
                    OCCURRED, READ_AT, "商品《高等数学》已通过审核", new ResourceRef("product", 42L)));
            when(queries.get(any(), eq(99L)))
                    .thenThrow(new BusinessError("RESOURCE_NOT_VISIBLE", 404, "通知不存在"));
            return queries;
        }

        @Bean
        NotificationReadCommand stubNotificationReadCommand() {
            JsonMapper json = JsonMapper.builder().build();
            var body = json.createObjectNode();
            body.put("notification_id", "11");
            body.put("read_at", READ_AT.toString());
            return (context, key, id) -> new WriteResult<>(UUID.randomUUID(), 200, body,
                    new ResourceRef("notification", id), false);
        }

        @Bean
        io.github.iy88.project1.api.CsrfGuard.Verifier stubCsrfVerifier() {
            return (request, token) -> CSRF_TOKEN.equals(token);
        }

        @Bean
        NotificationActorResolver stubNotificationActorResolver() {
            return request -> {
                if (request.getHeader(ANONYMOUS_HEADER) != null) {
                    throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "请先登录");
                }
                return new NotificationActorResolver.Actor(ACCOUNT, UUID.randomUUID(), 0L);
            };
        }
    }

    @Test
    void listsTheOwnNotificationsWithTheirUnreadTotal() throws Exception {
        mvc.perform(get("/api/v1/account/notifications")
                        .param("page", "2")
                        .param("page_size", "20")
                        .param("read", "unread")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.items[0].notification_id").value("11"))
                .andExpect(jsonPath("$.items[0].event_type").value("product_audit.passed"))
                .andExpect(jsonPath("$.items[0].read_at").value(nullValue()))
                .andExpect(jsonPath("$.items[0].source.resource_type").value("product"))
                .andExpect(jsonPath("$.items[0].source.resource_id").value("42"))
                .andExpect(jsonPath("$.page").value(2))
                .andExpect(jsonPath("$.page_size").value(20))
                .andExpect(jsonPath("$.total").value(21))
                .andExpect(jsonPath("$.unread_count").value(3));
    }

    @Test
    void rejectsAnUnknownReadFilter() throws Exception {
        mvc.perform(get("/api/v1/account/notifications").param("read", "sometimes"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"))
                .andExpect(jsonPath("$.request_id").exists());
    }

    @Test
    void rejectsAPageSizeAboveTheLimit() throws Exception {
        mvc.perform(get("/api/v1/account/notifications").param("page_size", "500"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"));
    }

    @Test
    void returnsOneNotificationWithItsFirstReadInstant() throws Exception {
        mvc.perform(get("/api/v1/account/notifications/11").accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.notification_id").value("11"))
                .andExpect(jsonPath("$.summary").value("商品《高等数学》已通过审核"))
                .andExpect(jsonPath("$.read_at").exists());
    }

    @Test
    void hidesANotificationOfAnotherAccount() throws Exception {
        mvc.perform(get("/api/v1/account/notifications/99"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_VISIBLE"));
    }

    @Test
    void treatsAnUnparseableIdAsNotVisible() throws Exception {
        mvc.perform(get("/api/v1/account/notifications/abc"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_VISIBLE"));
    }

    @Test
    void requiresACallerChosenIdempotencyKeyWhenRecordingARead() throws Exception {
        mvc.perform(put("/api/v1/account/notifications/11/read")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"));
    }

    @Test
    void recordsTheFirstRead() throws Exception {
        mvc.perform(put("/api/v1/account/notifications/11/read")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .header("Idempotency-Key", "read-11")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.notification_id").value("11"))
                .andExpect(jsonPath("$.read_at").exists());
    }

    @Test
    void refusesAWriteWithoutTheCsrfToken() throws Exception {
        mvc.perform(put("/api/v1/account/notifications/11/read")
                        .header("Origin", ORIGIN)
                        .header("Idempotency-Key", "read-11"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));
    }

    @Test
    void refusesAWriteFromAnUnlistedOrigin() throws Exception {
        mvc.perform(put("/api/v1/account/notifications/11/read")
                        .header("Origin", "http://evil.example")
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .header("Idempotency-Key", "read-11"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));
    }

    @Test
    void refusesAnUnauthenticatedCaller() throws Exception {
        mvc.perform(get("/api/v1/account/notifications").header(ANONYMOUS_HEADER, "1"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTHENTICATION_REQUIRED"));
    }
}
