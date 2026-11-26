package io.github.iy88.project1.api.conversation;

import com.fasterxml.jackson.annotation.JsonProperty;

/** JSON request bodies of API-CONV-001, 004 and 005. */
public final class ConversationRequests {
    private ConversationRequests() {
    }

    public record PrivateChat(@JsonProperty("target_account_id") String targetAccountId) {
    }

    public record Send(String body) {
    }

    public record Read(@JsonProperty("displayed_seq") Long displayedSeq) {
    }
}
