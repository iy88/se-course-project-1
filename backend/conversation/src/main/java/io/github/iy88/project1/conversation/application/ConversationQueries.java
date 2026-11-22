package io.github.iy88.project1.conversation.application;

import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.persistence.ChatConversation;
import io.github.iy88.project1.conversation.persistence.ChatMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.conversation.persistence.TradeConversation;
import io.github.iy88.project1.conversation.persistence.TradeMessage;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Service;

/** Read-only conversation queries; they never advance read progress. */
@Service
public class ConversationQueries {
    private final ConversationStore store;
    private final ConversationReader reader;
    private final AccountDirectory accounts;
    private final TradeParticipation trades;
    private final ConversationSettings settings;

    public ConversationQueries(ConversationStore store, ConversationReader reader, AccountDirectory accounts,
                               TradeParticipation trades, ConversationSettings settings) {
        this.store = store;
        this.reader = reader;
        this.accounts = accounts;
        this.trades = trades;
        this.settings = settings;
    }

    public ConversationViews.MessagePage pageChat(ExecutionContext context, long conversationId, Long beforeSeq,
                                                  Long afterSeq, int limit) {
        long actor = accountId(context);
        var conversation = store.chat(conversationId);
        if (!conversation.involves(actor)) {
            throw participantRequired();
        }
        if (beforeSeq != null && afterSeq != null) {
            throw new BusinessError("INPUT_INVALID", 422, "before_seq 与 after_seq 只能二选一");
        }
        var messages = reader.chatMessages(conversationId, beforeSeq, afterSeq, pageSize(limit));
        var senderIds = new HashSet<Long>();
        messages.forEach(message -> senderIds.add(message.senderAccountId()));
        var profiles = accounts.profiles(senderIds);
        var items = messages.stream().map(message -> chatMessage(message, profiles)).toList();
        return new ConversationViews.MessagePage(items, lastSeq(items), firstSeq(items), "active");
    }

    public ConversationViews.Page<ConversationViews.Summary> list(ExecutionContext context, int page, int pageSize) {
        long actor = accountId(context);
        int currentPage = Math.max(1, page);
        int size = pageSize(pageSize);

        var branches = new ArrayList<OwnedBranch>();
        for (ChatConversation conversation : reader.chatConversations(actor)) {
            branches.add(new OwnedBranch(conversation.otherAccount(actor), chatBranch(conversation, actor)));
        }
        var tradeIds = trades.tradeIdsOf(actor);
        for (TradeConversation conversation : reader.tradeConversations(tradeIds)) {
            var participants = trades.participants(conversation.tradeId()).orElse(null);
            if (participants == null || !participants.involves(actor)) {
                continue;
            }
            branches.add(new OwnedBranch(participants.peerOf(actor), tradeBranch(conversation, actor)));
        }

        var peers = new HashSet<Long>();
        branches.forEach(branch -> peers.add(branch.peerAccountId()));
        var profiles = accounts.profiles(peers);

        var grouped = new LinkedHashMap<Long, List<ConversationViews.Branch>>();
        for (OwnedBranch branch : branches) {
            grouped.computeIfAbsent(branch.peerAccountId(), key -> new ArrayList<>()).add(branch.branch());
        }
        var summaries = grouped.entrySet().stream()
                .map(entry -> new ConversationViews.Summary(
                        new ConversationViews.Peer(entry.getKey(), displayName(entry.getKey(), profiles)),
                        sortedBranches(entry.getValue())))
                .sorted(Comparator.comparing((ConversationViews.Summary summary) -> latest(summary.branches()))
                        .reversed())
                .toList();

        int from = Math.min((currentPage - 1) * size, summaries.size());
        int to = Math.min(from + size, summaries.size());
        return new ConversationViews.Page<>(summaries.subList(from, to), currentPage, size, summaries.size());
    }

    private ConversationViews.Branch chatBranch(ChatConversation conversation, long actor) {
        var last = reader.chatLastMessage(conversation.id()).orElse(null);
        Instant lastAt = last == null ? conversation.createdAt() : last.createdAt();
        return new ConversationViews.Branch("chat", conversation.id(), null, null,
                store.chatUnread(conversation, actor), lastAt, preview(last == null ? null : last.body()));
    }

    private ConversationViews.Branch tradeBranch(TradeConversation conversation, long actor) {
        var last = reader.tradeLastMessage(conversation.id()).orElse(null);
        Instant lastAt = last == null ? conversation.createdAt() : last.createdAt();
        return new ConversationViews.Branch("trade", conversation.id(), null, conversation.archivedAt(),
                store.tradeUnread(conversation, actor), lastAt, preview(last == null ? null : last.body()));
    }

    private ConversationViews.Message chatMessage(ChatMessage message, Map<Long, AccountDirectory.Profile> profiles) {
        return new ConversationViews.Message(message.id(), message.seq(),
                new ConversationViews.Sender(message.senderAccountId(),
                        displayName(message.senderAccountId(), profiles), "account"),
                "text", message.body(), message.createdAt(), null, null);
    }

    private static List<ConversationViews.Branch> sortedBranches(List<ConversationViews.Branch> branches) {
        return branches.stream()
                .sorted(Comparator.comparing(ConversationViews.Branch::lastMessageAt,
                        Comparator.nullsFirst(Comparator.naturalOrder())).reversed())
                .toList();
    }

    private static Instant latest(List<ConversationViews.Branch> branches) {
        return branches.stream()
                .map(ConversationViews.Branch::lastMessageAt)
                .filter(java.util.Objects::nonNull)
                .max(Comparator.naturalOrder())
                .orElse(Instant.EPOCH);
    }

    private String preview(String body) {
        if (body == null || body.isBlank()) {
            return "";
        }
        int max = settings.getPreviewLength();
        return body.length() <= max ? body : body.substring(0, max) + "…";
    }

    private static String displayName(long accountId, Map<Long, AccountDirectory.Profile> profiles) {
        var profile = profiles.get(accountId);
        return profile == null ? "账户" + accountId : profile.displayName();
    }

    private int pageSize(int limit) {
        if (limit <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, "limit 必须为正数");
        }
        return Math.min(limit, settings.getMaxPageSize());
    }

    private static Long firstSeq(List<ConversationViews.Message> items) {
        return items.isEmpty() ? null : items.getFirst().seq();
    }

    private static Long lastSeq(List<ConversationViews.Message> items) {
        return items.isEmpty() ? null : items.getLast().seq();
    }

    private static long accountId(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    private static BusinessError participantRequired() {
        return new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问");
    }

    private record OwnedBranch(long peerAccountId, ConversationViews.Branch branch) {
    }
}
