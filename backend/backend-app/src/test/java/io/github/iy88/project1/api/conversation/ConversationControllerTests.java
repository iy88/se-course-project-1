package io.github.iy88.project1.api.conversation;

import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import io.github.iy88.project1.conversation.ConversationKind;
import io.github.iy88.project1.conversation.application.ConversationQueries;
import io.github.iy88.project1.conversation.application.ConversationViews;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import java.util.Map;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest(properties = {
        "spring.autoconfigure.exclude=org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration,"
                + "org.springframework.boot.data.redis.autoconfigure.DataRedisAutoConfiguration",
        "project1.http.allowed-origins=http://127.0.0.1:3000"})
@AutoConfigureMockMvc
class ConversationControllerTests {
    private static final Instant NOW = Instant.parse("2026-11-23T10:00:00Z");
    private static final long ACCOUNT = 7L;
    private static final String ANONYMOUS_HEADER = "X-Test-Anonymous";
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final String CSRF_TOKEN = "test-csrf";
    private static final JsonMapper JSON = JsonMapper.builder().build();

    @Autowired
    private MockMvc mvc;

    @TestConfiguration
    static class Stubs {
        @Bean
        @Primary
        ConversationQueries stubConversationQueries() {
            var queries = mock(ConversationQueries.class);
            when(queries.list(any(), anyInt(), anyInt())).thenReturn(new ConversationViews.Page<>(
                    List.of(new ConversationViews.Summary(
                            new ConversationViews.Peer(42L, "李四", "https://img.example/peer.png"),
                            List.of(new ConversationViews.Branch("trade", 2L, null, null, 1L, NOW, "在吗")))),
                    1, 20, 1));
            when(queries.pageTrade(any(), eq(2L), any(), any(), anyInt())).thenReturn(
                    new ConversationViews.MessagePage(List.of(
                            new ConversationViews.Message(21L, 2L,
                                    new ConversationViews.Sender(7L, "张新悦", "account"),
                                    "text", "在吗", NOW, null, null)), 2L, 2L, "active", 19L));
            when(queries.pageChat(any(), anyLong(), any(), any(), anyInt()))
                    .thenThrow(new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问"));
            return queries;
        }

        @Bean
        ConversationWriteCommands stubConversationWriteCommands() {
            return new ConversationWriteCommands() {
                @Override
                public WriteResult<JsonNode> startPrivate(io.github.iy88.project1.core.ExecutionContext context,
                                                          String key, long targetAccountId) {
                    return result(200, "chat", 5L, Map.of(
                            "conversation_kind", "chat",
                            "conversation_id", "5",
                            "peer", Map.of("account_id", "42", "display_name", "李四"),
                            "reused", false));
                }

                @Override
                public WriteResult<JsonNode> send(io.github.iy88.project1.core.ExecutionContext context, String key,
                                                  ConversationKind kind, long conversationId, String body) {
                    return result(201, kind.wireValue(), conversationId, Map.of(
                            "message_id", "21",
                            "seq", 2,
                            "created_at", NOW.toString(),
                            "sender", Map.of("account_id", "7", "display_name", "张新悦", "sender_kind", "account"),
                            "unread_count", 1));
                }

                @Override
                public WriteResult<JsonNode> markRead(io.github.iy88.project1.core.ExecutionContext context,
                                                      String key, ConversationKind kind, long conversationId,
                                                      long displayedSeq) {
                    return result(200, kind.wireValue(), conversationId, Map.of(
                            "last_read_seq", 2,
                            "unread_count", 0,
                            "updated_at", NOW.toString()));
                }

                private static WriteResult<JsonNode> result(int status, String type, long id, Map<String, Object> body) {
                    return new WriteResult<>(UUID.randomUUID(), status, JSON.valueToTree(body),
                            new ResourceRef(type, id), false);
                }
            };
        }

        @Bean
        io.github.iy88.project1.api.CsrfGuard.Verifier stubCsrfVerifier() {
            return (request, token) -> CSRF_TOKEN.equals(token);
        }

        @Bean
        ConversationActorResolver stubConversationActorResolver() {
            return new ConversationActorResolver() {
                @Override
                public Actor resolve(HttpServletRequest request) {
                    if (request.getHeader(ANONYMOUS_HEADER) != null) {
                        throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "请先登录");
                    }
                    return new Actor(ACCOUNT, UUID.randomUUID(), 0L);
                }
            };
        }
    }

    @Test
    void listsChatAndTradeBranches() throws Exception {
        mvc.perform(get("/api/v1/conversations").param("page", "1").param("page_size", "20")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.items[0].peer.account_id").value("42"))
                .andExpect(jsonPath("$.items[0].peer.display_name").value("李四"))
                .andExpect(jsonPath("$.items[0].peer.avatar_url").value("https://img.example/peer.png"))
                .andExpect(jsonPath("$.items[0].branches[0].conversation_kind").value("trade"))
                .andExpect(jsonPath("$.items[0].branches[0].conversation_id").value("2"))
                .andExpect(jsonPath("$.items[0].branches[0].source_ref").value(nullValue()))
                .andExpect(jsonPath("$.items[0].branches[0].unread_count").value(1))
                .andExpect(jsonPath("$.page").value(1))
                .andExpect(jsonPath("$.page_size").value(20))
                .andExpect(jsonPath("$.total").value(1));
    }

    @Test
    void returnsTradeMessagesWithTradeIdCursorsAndBranchStatus() throws Exception {
        mvc.perform(get("/api/v1/conversations/trade/2/messages").param("after_seq", "0").param("limit", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].message_id").value("21"))
                .andExpect(jsonPath("$.items[0].message_type").value("text"))
                .andExpect(jsonPath("$.items[0].sender.sender_kind").value("account"))
                .andExpect(jsonPath("$.items[0].seq").value(2))
                .andExpect(jsonPath("$.next_after_seq").value(2))
                .andExpect(jsonPath("$.next_before_seq").value(2))
                .andExpect(jsonPath("$.branch_status").value("active"))
                .andExpect(jsonPath("$.trade_id").value("19"));
    }

    @Test
    void rejectsUnknownKindAndHidesCaseUntilTheCaseAdapterExists() throws Exception {
        mvc.perform(get("/api/v1/conversations/group/2/messages"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"));
        mvc.perform(get("/api/v1/conversations/case/2/messages"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("DEPENDENCY_UNAVAILABLE"));
    }

    @Test
    void startsAPrivateChat() throws Exception {
        mvc.perform(post("/api/v1/conversations/private")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .header("Idempotency-Key", "private-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"target_account_id\":\"42\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversation_kind").value("chat"))
                .andExpect(jsonPath("$.conversation_id").value("5"))
                .andExpect(jsonPath("$.peer.account_id").value("42"))
                .andExpect(jsonPath("$.reused").value(false));
    }

    @Test
    void sendsATradeMessageWithAnIdempotencyKey() throws Exception {
        mvc.perform(post("/api/v1/conversations/trade/2/messages")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .header("Idempotency-Key", "send-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"body\":\"在吗\"}"))
                .andExpect(status().isCreated())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.message_id").value("21"))
                .andExpect(jsonPath("$.seq").value(2))
                .andExpect(jsonPath("$.unread_count").value(1));
    }

    @Test
    void requiresAnIdempotencyKeyAndNonEmptyBody() throws Exception {
        mvc.perform(post("/api/v1/conversations/trade/2/messages")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"body\":\"在吗\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"));
        mvc.perform(post("/api/v1/conversations/trade/2/messages")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .header("Idempotency-Key", "send-2")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"body\":\"  \"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"));
    }

    @Test
    void advancesReadProgress() throws Exception {
        mvc.perform(post("/api/v1/conversations/trade/2/read-progress")
                        .header("Origin", ORIGIN)
                        .header("X-CSRF-Token", CSRF_TOKEN)
                        .header("Idempotency-Key", "read-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"displayed_seq\":2}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.last_read_seq").value(2))
                .andExpect(jsonPath("$.unread_count").value(0));
    }

    @Test
    void refusesAWriteWithoutTheCsrfToken() throws Exception {
        mvc.perform(post("/api/v1/conversations/trade/2/messages")
                        .header("Origin", ORIGIN)
                        .header("Idempotency-Key", "send-3")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"body\":\"在吗\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));
    }

    @Test
    void refusesAnUnauthenticatedCaller() throws Exception {
        mvc.perform(get("/api/v1/conversations").header(ANONYMOUS_HEADER, "1"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTHENTICATION_REQUIRED"));
    }
}
