package io.github.iy88.project1.conversation.persistence;

import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.ConversationRules;
import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.MessageSenderKind;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Transactional conversation primitives. Callers own the transaction and the lock plan; these
 * methods never commit and never resolve participant eligibility beyond the conversation row.
 */
@Service
public class ConversationStore {
    private static final long MAX_SAFE_SEQUENCE = 9007199254740991L;

    private final ChatConversationRepository chats;
    private final TradeConversationRepository trades;
    private final CaseConversationRepository cases;
    private final ChatMessageRepository chatMessages;
    private final TradeMessageRepository tradeMessages;
    private final CaseMessageRepository caseMessages;
    private final ChatReadProgressRepository chatProgress;
    private final TradeReadProgressRepository tradeProgress;
    private final CaseReadProgressRepository caseProgress;
    private final JdbcClient jdbc;
    private final ConversationSettings settings;
    private final Clock clock;

    public ConversationStore(ChatConversationRepository chats, TradeConversationRepository trades,
                             CaseConversationRepository cases, ChatMessageRepository chatMessages,
                             TradeMessageRepository tradeMessages, CaseMessageRepository caseMessages,
                             ChatReadProgressRepository chatProgress, TradeReadProgressRepository tradeProgress,
                             CaseReadProgressRepository caseProgress, JdbcClient jdbc,
                             ConversationSettings settings, Clock clock) {
        this.chats = chats;
        this.trades = trades;
        this.cases = cases;
        this.chatMessages = chatMessages;
        this.tradeMessages = tradeMessages;
        this.caseMessages = caseMessages;
        this.chatProgress = chatProgress;
        this.tradeProgress = tradeProgress;
        this.caseProgress = caseProgress;
        this.jdbc = jdbc;
        this.settings = settings;
        this.clock = clock;
    }

    public ChatConversation ensureChat(WriteTransaction transaction, long firstAccountId, long secondAccountId) {
        var pair = ConversationRules.pair(firstAccountId, secondAccountId);
        var now = clock.instant();
        int inserted = jdbc.sql("""
                        insert into chat_conversation (account_low_id, account_high_id, created_at)
                        values (:low, :high, :createdAt)
                        on conflict (account_low_id, account_high_id) do nothing
                        """)
                .param("low", pair.lowAccountId())
                .param("high", pair.highAccountId())
                .param("createdAt", now)
                .update();
        var conversation = chats.findByAccountLowIdAndAccountHighId(pair.lowAccountId(), pair.highAccountId())
                .orElseThrow(() -> new IllegalStateException("Chat conversation was not persisted"));
        if (inserted == 1) {
            chatProgress.save(new ChatReadProgress(conversation.id(), conversation.accountLowId()));
            chatProgress.save(new ChatReadProgress(conversation.id(), conversation.accountHighId()));
        }
        return conversation;
    }

    public Optional<ChatConversation> findChat(long firstAccountId, long secondAccountId) {
        var pair = ConversationRules.pair(firstAccountId, secondAccountId);
        return chats.findByAccountLowIdAndAccountHighId(pair.lowAccountId(), pair.highAccountId());
    }

    public ChatConversation lockChat(WriteTransaction transaction, long conversationId) {
        var holder = new AtomicReference<ChatConversation>();
        transaction.lock(key(LockPlan.Domain.CHAT_CONVERSATION, conversationId),
                () -> holder.set(chats.lockById(conversationId).orElseThrow(ConversationStore::participantRequired)));
        return holder.get();
    }

    public ChatConversation chat(long conversationId) {
        return chats.findById(conversationId).orElseThrow(ConversationStore::participantRequired);
    }

    public TradeConversation trade(long conversationId) {
        return trades.findById(conversationId).orElseThrow(ConversationStore::participantRequired);
    }

    public CaseConversation caseConversation(long conversationId) {
        return cases.findById(conversationId).orElseThrow(ConversationStore::participantRequired);
    }

    public Optional<CaseConversation> findCase(long caseId, long relatedAccountId) {
        return cases.findByCaseIdAndRelatedAccountId(caseId, relatedAccountId);
    }

    public CaseConversation lockCaseByCase(WriteTransaction transaction, long caseId, long relatedAccountId) {
        var conversation = findCase(caseId, relatedAccountId).orElseThrow(ConversationStore::participantRequired);
        return lockCase(transaction, conversation.id());
    }

    public ChatMessage appendChatText(WriteTransaction transaction, ChatConversation conversation,
                                      long senderAccountId, String body) {
        if (!conversation.involves(senderAccountId)) {
            throw participantRequired();
        }
        var text = requireBody(body);
        var message = new ChatMessage(conversation.id(), allocate(conversation.seqHead(), conversation::allocateSeq),
                senderAccountId, text, clock.instant());
        return chatMessages.save(message);
    }

    public ChatReadProgress advanceChatRead(WriteTransaction transaction, ChatConversation conversation,
                                            long accountId, long displayedSeq) {
        if (!conversation.involves(accountId)) {
            throw participantRequired();
        }
        requireDisplayedSequence(conversation.seqHead(), displayedSeq);
        transaction.lock(key(LockPlan.Domain.READ_PROGRESS, conversation.id(), accountId), () -> {
        });
        var progress = chatProgress.lockByConversationAndAccount(conversation.id(), accountId)
                .orElseGet(() -> chatProgress.save(new ChatReadProgress(conversation.id(), accountId)));
        progress.advanceTo(displayedSeq, clock.instant());
        return chatProgress.save(progress);
    }

    public long chatUnread(ChatConversation conversation, long accountId) {
        return chatProgress.findByChatConversationIdAndAccountId(conversation.id(), accountId)
                .map(progress -> ConversationRules.unreadCount(conversation.seqHead(), progress.lastReadSeq()))
                .orElse(conversation.seqHead());
    }

    public TradeConversation ensureTrade(WriteTransaction transaction, long tradeId, long buyerId, long sellerId) {
        if (buyerId == sellerId) {
            throw new IllegalArgumentException("A trade needs two distinct accounts");
        }
        int inserted = jdbc.sql("""
                        insert into trade_conversation (trade_id, created_at)
                        values (:tradeId, :createdAt)
                        on conflict (trade_id) do nothing
                        """)
                .param("tradeId", tradeId)
                .param("createdAt", clock.instant())
                .update();
        var conversation = trades.findByTradeId(tradeId)
                .orElseThrow(() -> new IllegalStateException("Trade conversation was not persisted"));
        if (inserted == 1) {
            tradeProgress.save(new TradeReadProgress(conversation.id(), buyerId));
            tradeProgress.save(new TradeReadProgress(conversation.id(), sellerId));
        }
        return conversation;
    }

    public Optional<TradeConversation> findTrade(long tradeId) {
        return trades.findByTradeId(tradeId);
    }

    public TradeConversation lockTrade(WriteTransaction transaction, long conversationId) {
        var holder = new AtomicReference<TradeConversation>();
        transaction.lock(key(LockPlan.Domain.TRADE_CONVERSATION, conversationId),
                () -> holder.set(trades.lockById(conversationId).orElseThrow(ConversationStore::participantRequired)));
        return holder.get();
    }

    public TradeConversation lockTradeByTradeId(WriteTransaction transaction, long tradeId) {
        var conversation = trades.findByTradeId(tradeId).orElseThrow(ConversationStore::participantRequired);
        return lockTrade(transaction, conversation.id());
    }

    public TradeMessage appendTradeText(WriteTransaction transaction, TradeConversation conversation,
                                        long senderAccountId, String body) {
        requireActive(conversation);
        var text = requireBody(body);
        var message = TradeMessage.text(conversation.id(),
                allocate(conversation.seqHead(), conversation::allocateSeq), senderAccountId,
                text, clock.instant());
        return tradeMessages.save(message);
    }

    /**
     * System events are idempotent by business event id: a retry returns the persisted message
     * instead of appending a second snapshot.
     */
    public TradeMessage appendTradeSystemEvent(WriteTransaction transaction, TradeConversation conversation,
                                               UUID businessEventId, String eventType, String body,
                                               String sourceType, Long sourceId) {
        if (businessEventId == null || eventType == null || eventType.isBlank()) {
            throw new IllegalArgumentException("A trade system event needs an id and a type");
        }
        if ((sourceType == null) != (sourceId == null)) {
            throw new IllegalArgumentException("A trade source reference needs both type and id");
        }
        var existing = tradeMessages.findByBusinessEventId(businessEventId);
        if (existing.isPresent()) {
            return existing.get();
        }
        requireActive(conversation);
        var text = requireBody(body);
        var message = TradeMessage.systemEvent(conversation.id(),
                allocate(conversation.seqHead(), conversation::allocateSeq), businessEventId, eventType,
                text, sourceType, sourceId, clock.instant());
        return tradeMessages.save(message);
    }

    public boolean archiveTrade(WriteTransaction transaction, TradeConversation conversation) {
        if (!conversation.archive(clock.instant())) {
            return false;
        }
        trades.save(conversation);
        return true;
    }

    public TradeReadProgress advanceTradeRead(WriteTransaction transaction, TradeConversation conversation,
                                              long accountId, long displayedSeq) {
        requireDisplayedSequence(conversation.seqHead(), displayedSeq);
        transaction.lock(key(LockPlan.Domain.READ_PROGRESS, conversation.id(), accountId), () -> {
        });
        var progress = tradeProgress.lockByConversationAndAccount(conversation.id(), accountId)
                .orElseThrow(ConversationStore::participantRequired);
        progress.advanceTo(displayedSeq, clock.instant());
        return tradeProgress.save(progress);
    }

    public long tradeUnread(TradeConversation conversation, long accountId) {
        return tradeProgress.findByTradeConversationIdAndAccountId(conversation.id(), accountId)
                .map(progress -> ConversationRules.unreadCount(conversation.seqHead(), progress.lastReadSeq()))
                .orElse(conversation.seqHead());
    }

    public CaseConversation ensureCase(WriteTransaction transaction, long caseId, long relatedAccountId) {
        int inserted = jdbc.sql("""
                        insert into case_conversation (case_id, related_account_id, created_at)
                        values (:caseId, :accountId, :createdAt)
                        on conflict (case_id, related_account_id) do nothing
                        """)
                .param("caseId", caseId)
                .param("accountId", relatedAccountId)
                .param("createdAt", clock.instant())
                .update();
        var conversation = cases.findByCaseIdAndRelatedAccountId(caseId, relatedAccountId)
                .orElseThrow(() -> new IllegalStateException("Case conversation was not persisted"));
        if (inserted == 1) {
            caseProgress.save(new CaseReadProgress(conversation.id(), relatedAccountId));
        }
        return conversation;
    }

    public CaseConversation lockCase(WriteTransaction transaction, long conversationId) {
        var holder = new AtomicReference<CaseConversation>();
        transaction.lock(key(LockPlan.Domain.CASE_CONVERSATION, conversationId),
                () -> holder.set(cases.lockById(conversationId).orElseThrow(ConversationStore::participantRequired)));
        return holder.get();
    }

    public CaseMessage appendCaseMessage(WriteTransaction transaction, CaseConversation conversation,
                                         CaseMessageKind kind, MessageSenderKind senderKind, long senderAccountId,
                                         String body) {
        requireActive(conversation);
        requireCaseRole(kind, senderKind);
        var text = requireBody(body);
        var message = CaseMessage.participant(conversation.id(),
                allocate(conversation.seqHead(), conversation::allocateSeq), kind, senderKind,
                senderAccountId, text, clock.instant());
        return caseMessages.save(message);
    }

    public CaseMessage appendCaseSystemEvent(WriteTransaction transaction, CaseConversation conversation,
                                             UUID businessEventId, String eventType, String body) {
        if (businessEventId == null || eventType == null || eventType.isBlank()) {
            throw new IllegalArgumentException("A case system event needs an id and a type");
        }
        var existing = caseMessages.findByBusinessEventId(businessEventId);
        if (existing.isPresent()) {
            return existing.get();
        }
        requireActive(conversation);
        var text = requireBody(body);
        var message = CaseMessage.systemNotice(conversation.id(),
                allocate(conversation.seqHead(), conversation::allocateSeq), businessEventId, eventType,
                text, clock.instant());
        return caseMessages.save(message);
    }

    public boolean archiveCase(WriteTransaction transaction, CaseConversation conversation) {
        if (!conversation.archive(clock.instant())) {
            return false;
        }
        cases.save(conversation);
        return true;
    }

    public CaseReadProgress advanceCaseRead(WriteTransaction transaction, CaseConversation conversation,
                                            long accountId, long displayedSeq) {
        requireDisplayedSequence(conversation.seqHead(), displayedSeq);
        transaction.lock(key(LockPlan.Domain.READ_PROGRESS, conversation.id(), accountId), () -> {
        });
        var progress = caseProgress.lockByConversationAndAccount(conversation.id(), accountId)
                .orElseThrow(ConversationStore::participantRequired);
        progress.advanceTo(displayedSeq, clock.instant());
        return caseProgress.save(progress);
    }

    public long caseUnread(CaseConversation conversation, long accountId) {
        return caseProgress.findByCaseConversationIdAndAccountId(conversation.id(), accountId)
                .map(progress -> ConversationRules.unreadCount(conversation.seqHead(), progress.lastReadSeq()))
                .orElse(conversation.seqHead());
    }

    private long allocate(long seqHead, java.util.function.LongSupplier allocator) {
        if (seqHead >= MAX_SAFE_SEQUENCE) {
            throw new BusinessError("STATE_CONFLICT", 409, "会话序号已用尽");
        }
        return allocator.getAsLong();
    }

    private String requireBody(String body) {
        if (body == null || body.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "消息内容不能为空");
        }
        if (body.length() > settings.getMaxBodyLength()) {
            throw new BusinessError("INPUT_INVALID", 422, "消息内容超出长度限制");
        }
        return body;
    }

    private static void requireDisplayedSequence(long seqHead, long displayedSeq) {
        if (displayedSeq < 0 || displayedSeq > seqHead) {
            throw new BusinessError("INPUT_INVALID", 422, "已读序号超出会话范围");
        }
    }

    private static void requireActive(TradeConversation conversation) {
        if (conversation.archived()) {
            throw new BusinessError("BRANCH_ARCHIVED", 409, "会话已归档");
        }
    }

    private static void requireActive(CaseConversation conversation) {
        if (conversation.archived()) {
            throw new BusinessError("BRANCH_ARCHIVED", 409, "会话已归档");
        }
    }

    private static void requireCaseRole(CaseMessageKind kind, MessageSenderKind senderKind) {
        boolean valid = switch (senderKind) {
            case ACCOUNT -> kind == CaseMessageKind.STATEMENT || kind == CaseMessageKind.APPEAL;
            case MANAGER -> kind == CaseMessageKind.INQUIRY || kind == CaseMessageKind.MANAGER_REPLY;
            case SYSTEM -> throw new IllegalArgumentException("System notices use appendCaseSystemEvent");
        };
        if (!valid) {
            throw new BusinessError("ACTION_NOT_ALLOWED", 403, "消息类型与发送角色不匹配");
        }
    }

    private static BusinessError participantRequired() {
        return new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问");
    }

    private static LockPlan.Key key(LockPlan.Domain domain, long... parts) {
        var identifiers = new ArrayList<Long>(parts.length);
        for (long part : parts) {
            identifiers.add(part);
        }
        return new LockPlan.Key(domain, List.copyOf(identifiers));
    }
}
