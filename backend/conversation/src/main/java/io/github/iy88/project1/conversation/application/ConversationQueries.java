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
import org.springframework.context.annotation.Lazy;
import org.jspecify.annotations.Nullable;
import org.springframework.stereotype.Service;

/** Read-only conversation queries; they never advance read progress. */
@Lazy
@Service
public class ConversationQueries {
    private final ConversationStore store;
    private final ConversationReader reader;
    private final AccountDirectory accounts;
    private final TradeParticipation trades;
    private final ConversationSettings settings;

    public ConversationQueries(ConversationStore store, ConversationReader reader, AccountDirectory accounts,
                               @Nullable TradeParticipation trades, ConversationSettings settings) {
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
        return new ConversationViews.MessagePage(items, lastSeq(items), firstSeq(items), "active", null);
    }

    public ConversationViews.MessagePage pageTrade(ExecutionContext context, long conversationId, Long beforeSeq,
                                                   Long afterSeq, int limit) {
        long actor = accountId(context);
        var conversation = store.trade(conversationId);
        var participants = tradesOf().participants(conversation.tradeId()).orElse(null);
        if (participants == null || !participants.involves(actor)) {
            throw participantRequired();
        }
        if (beforeSeq != null && afterSeq != null) {
            throw new BusinessError("INPUT_INVALID", 422, "before_seq 与 after_seq 只能二选一");
        }
        var messages = reader.tradeMessages(conversationId, beforeSeq, afterSeq, pageSize(limit));
        var senderIds = new HashSet<Long>();
        for (TradeMessage message : messages) {
            if (message.senderAccountId() != null) {
                senderIds.add(message.senderAccountId());
            }
        }
        var profiles = accounts.profiles(senderIds);
        var items = messages.stream().map(message -> tradeMessage(message, conversation.tradeId(), profiles)).toList();
        return new ConversationViews.MessagePage(items, lastSeq(items), firstSeq(items),
                conversation.archived() ? "archived" : "active", conversation.tradeId());
    }

    public ConversationViews.Page<ConversationViews.Summary> list(ExecutionContext context, int page, int pageSize) {
        long actor = accountId(context);
        int currentPage = Math.max(1, page);
        int size = pageSize(pageSize);

        var branches = new ArrayList<OwnedBranch>();
        for (ChatConversation conversation : reader.chatConversations(actor)) {
            branches.add(new OwnedBranch(conversation.otherAccount(actor), chatBranch(conversation, actor)));
        }
        var tradeIds = trades == null ? Set.<Long>of() : trades.tradeIdsOf(actor);
        for (TradeConversation conversation : reader.tradeConversations(tradeIds)) {
            var participants = tradesOf().participants(conversation.tradeId()).orElse(null);
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
                        peer(entry.getKey(), profiles),
                        sortedBranches(entry.getValue())))
                .sorted(Comparator.comparing((ConversationViews.Summary summary) -> latest(summary.branches()))
                        .reversed())
                .toList();

        // Use a long offset so an oversized page cannot overflow into a negative index.
        long offset = (long) (currentPage - 1) * size;
        int from = (int) Math.min(offset, summaries.size());
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
        return new ConversationViews.Branch("trade", conversation.id(), "trade:" + conversation.tradeId(),
                conversation.archivedAt(), store.tradeUnread(conversation, actor), lastAt,
                preview(last == null ? null : last.body()));
    }

    private ConversationViews.Message chatMessage(ChatMessage message, Map<Long, AccountDirectory.Profile> profiles) {
        return new ConversationViews.Message(message.id(), message.seq(),
                new ConversationViews.Sender(message.senderAccountId(),
                        displayName(message.senderAccountId(), profiles), "account"),
                "text", message.body(), message.createdAt(), null, null);
    }

    private ConversationViews.Message tradeMessage(TradeMessage message, long tradeId,
                                                    Map<Long, AccountDirectory.Profile> profiles) {
        var sender = "system".equals(message.senderKind())
                ? new ConversationViews.Sender(null, "系统", "system")
                : new ConversationViews.Sender(message.senderAccountId(),
                        displayName(message.senderAccountId(), profiles), "account");
        String sourceRef = null;
        if ("system".equals(message.senderKind()) && message.sourceType() != null && message.sourceId() != null) {
            sourceRef = tradesOf().visibleSourceRef(tradeId, message.sourceType(), message.sourceId())
                    .orElse(null);
        }
        return new ConversationViews.Message(message.id(), message.seq(), sender, message.messageType(),
                message.body(), message.createdAt(), message.eventType(), sourceRef);
    }

    private static List<ConversationViews.Branch> sortedBranches(List<ConversationViews.Branch> branches) {
        return branches.stream()
                .sorted(Comparator.comparing((ConversationViews.Branch element) -> element.lastMessageAt(),
                        Comparator.nullsFirst(Comparator.naturalOrder())).reversed())
                .toList();
    }

    private static Instant latest(List<ConversationViews.Branch> branches) {
        return branches.stream()
                .map(element -> element.lastMessageAt())
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

    private TradeParticipation tradesOf() {
        if (trades == null) {
            // Trade conversations are owned by the trade module; until its port is assembled the
            // read answers 503 rather than an empty or fabricated history.
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "交易会话由交易模块提供");
        }
        return trades;
    }

    private static String displayName(long accountId, Map<Long, AccountDirectory.Profile> profiles) {
        var profile = profiles.get(accountId);
        return profile == null ? "账户" + accountId : profile.displayName();
    }

    private static ConversationViews.Peer peer(long accountId,
                                               Map<Long, AccountDirectory.Profile> profiles) {
        var profile = profiles.get(accountId);
        return new ConversationViews.Peer(accountId, displayName(accountId, profiles),
                profile == null ? null : profile.avatarUrl());
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
