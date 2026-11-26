package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.conversation.ConversationKind;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteResult;
import tools.jackson.databind.JsonNode;

/** Browser write actions of API-CONV-001, 004 and 005, each owning one shared write transaction. */
public interface ConversationWriteCommands {
    WriteResult<JsonNode> startPrivate(ExecutionContext context, String idempotencyKey, long targetAccountId);

    WriteResult<JsonNode> send(ExecutionContext context, String idempotencyKey, ConversationKind kind,
                               long conversationId, String body);

    WriteResult<JsonNode> markRead(ExecutionContext context, String idempotencyKey, ConversationKind kind,
                                   long conversationId, long displayedSeq);

    /** Case threads advance read progress through the related account's own thread. */
    WriteResult<JsonNode> markCaseRead(ExecutionContext context, String idempotencyKey, long conversationId,
                                       long displayedSeq);
}
