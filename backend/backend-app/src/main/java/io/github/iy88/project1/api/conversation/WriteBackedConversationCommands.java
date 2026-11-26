package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.conversation.ConversationKind;
import io.github.iy88.project1.conversation.application.CaseConversations;
import io.github.iy88.project1.conversation.application.ConversationViews;
import io.github.iy88.project1.conversation.application.Conversations;
import io.github.iy88.project1.conversation.application.TradeChats;
import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.BusinessEventIntents;
import io.github.iy88.project1.messaging.RealtimeEventSources;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Binds the conversation write actions onto the shared write executor. Each action owns one
 * transaction and one idempotency scope; account locks are declared for both parties before the
 * service re-checks eligibility, and conversation row locks are recorded inside the transaction.
 */
public class WriteBackedConversationCommands implements ConversationWriteCommands {
    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final WriteExecutor writes;
    private final Conversations conversations;
    private final TradeChats tradeChats;
    private final ConversationStore store;
    private final TradeParticipation trades;
    private final CaseConversations caseConversations;

    public WriteBackedConversationCommands(WriteExecutor writes, Conversations conversations, TradeChats tradeChats,
                                           ConversationStore store, TradeParticipation trades,
                                           CaseConversations caseConversations) {
        this.writes = writes;
        this.conversations = conversations;
        this.tradeChats = tradeChats;
        this.store = store;
        this.trades = trades;
        this.caseConversations = caseConversations;
    }

    @Override
    public WriteResult<JsonNode> startPrivate(ExecutionContext context, String idempotencyKey, long targetAccountId) {
        return writes.run(context, "conversation.start_private", idempotencyKey, new StartRequest(targetAccountId),
                new StartUseCase(conversations));
    }

    @Override
    public WriteResult<JsonNode> send(ExecutionContext context, String idempotencyKey, ConversationKind kind,
                                      long conversationId, String body) {
        requireTrade(kind);
        return writes.run(context, "conversation.send", idempotencyKey,
                new SendRequest(kind, conversationId, body),
                new SendUseCase(conversations, tradeChats, store, trades));
    }

    @Override
    public WriteResult<JsonNode> markRead(ExecutionContext context, String idempotencyKey, ConversationKind kind,
                                          long conversationId, long displayedSeq) {
        requireTrade(kind);
        return writes.run(context, "conversation.mark_read", idempotencyKey,
                new ReadRequest(kind, conversationId, displayedSeq),
                new ReadUseCase(conversations, tradeChats));
    }

    private void requireTrade(ConversationKind kind) {
        if (kind == ConversationKind.TRADE && trades == null) {
            // Trade conversations are owned by the trade module; until its port is assembled the
            // write answers 503 instead of failing inside the transaction.
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "交易会话由交易模块提供");
        }
    }

    @Override
    public WriteResult<JsonNode> markCaseRead(ExecutionContext context, String idempotencyKey, long conversationId,
                                              long displayedSeq) {
        return writes.run(context, "conversation.mark_case_read", idempotencyKey,
                new CaseReadRequest(conversationId, displayedSeq),
                new CaseReadUseCase(caseConversations));

    }

    private record StartRequest(long targetAccountId) {
    }

    private record SendRequest(ConversationKind kind, long conversationId, String body) {
    }

    private record ReadRequest(ConversationKind kind, long conversationId, long displayedSeq) {
    }

    private record CaseReadRequest(long conversationId, long displayedSeq) {
    }

    private static final class StartUseCase implements WriteExecutor.UseCase<StartRequest, StartRequest> {
        private final Conversations conversations;

        private StartUseCase(Conversations conversations) {
            this.conversations = conversations;
        }

        @Override
        public JsonNode digestInput(StartRequest request) {
            var node = JSON.createObjectNode();
            node.put("target_account_id", Long.toString(request.targetAccountId()));
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, StartRequest request) {
            return new LockPlan(Map.of(request.targetAccountId(), LockPlan.AccountMode.SHARED), Set.of());
        }

        @Override
        public StartRequest qualify(ExecutionContext context, StartRequest request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, StartRequest qualification, ResourceRef resource) {
            if (!"chat".equals(resource.type()) || resource.id() <= 0) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "会话不存在");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, StartRequest request,
                                             StartRequest qualification, LockPlan plan) {
            ConversationViews.StartedChat started =
                    conversations.startPrivateChat(transaction, transaction.context(), request.targetAccountId());
            return new WriteResult.Response<>(200, ConversationWire.started(started),
                    new ResourceRef("chat", started.conversationId()));
        }
    }

    private static final class SendUseCase implements WriteExecutor.UseCase<SendRequest, SendRequest> {
        private final Conversations conversations;
        private final TradeChats tradeChats;
        private final ConversationStore store;
        private final TradeParticipation trades;

        private SendUseCase(Conversations conversations, TradeChats tradeChats, ConversationStore store,
                            TradeParticipation trades) {
            this.conversations = conversations;
            this.tradeChats = tradeChats;
            this.store = store;
            this.trades = trades;
        }

        @Override
        public JsonNode digestInput(SendRequest request) {
            var node = JSON.createObjectNode();
            node.put("conversation_kind", request.kind().wireValue());
            node.put("conversation_id", Long.toString(request.conversationId()));
            node.put("body", request.body());
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, SendRequest request) {
            long actor = Long.parseLong(context.actorId());
            long peer = peer(request, actor);
            var accounts = peer > 0 ? Map.of(peer, LockPlan.AccountMode.SHARED) : Map.<Long, LockPlan.AccountMode>of();
            return new LockPlan(accounts, Set.of(conversationKey(request.kind(), request.conversationId())));
        }

        @Override
        public SendRequest qualify(ExecutionContext context, SendRequest request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, SendRequest request, ResourceRef resource) {
            if (!request.kind().wireValue().equals(resource.type()) || resource.id() != request.conversationId()) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "会话不存在");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, SendRequest request,
                                             SendRequest qualification, LockPlan plan) {
            ConversationViews.ChatMessage message = request.kind() == ConversationKind.CHAT
                    ? conversations.sendChat(transaction, transaction.context(), request.conversationId(),
                    request.body())
                    : tradeChats.send(transaction, transaction.context(), request.conversationId(), request.body());
            long actor = Long.parseLong(transaction.context().actorId());
            long recipient = peer(request, actor);
            var reference = realtimeReference(request.kind(), request.conversationId());
            BusinessEventIntents.messageCreated(transaction, Set.of(actor, recipient), reference, message.messageId(),
                    "message_created:" + reference.kind().wireName() + ":" + message.messageId());
            BusinessEventIntents.messageRead(transaction, reference, message.seq(), "message_read:" + transaction.operationId());
            return new WriteResult.Response<>(201, ConversationWire.sent(message),
                    new ResourceRef(request.kind().wireValue(), request.conversationId()));
        }

        private long peer(SendRequest request, long actor) {
            if (request.kind() == ConversationKind.CHAT) {
                var conversation = store.chat(request.conversationId());
                return conversation.involves(actor) ? conversation.otherAccount(actor) : 0L;
            }
            var conversation = store.trade(request.conversationId());
            if (trades == null) {
                return 0L;
            }
            var participants = trades.participants(conversation.tradeId()).orElse(null);
            return participants != null && participants.involves(actor) ? participants.peerOf(actor) : 0L;
        }
    }

    private static final class ReadUseCase implements WriteExecutor.UseCase<ReadRequest, ReadRequest> {
        private final Conversations conversations;
        private final TradeChats tradeChats;

        private ReadUseCase(Conversations conversations, TradeChats tradeChats) {
            this.conversations = conversations;
            this.tradeChats = tradeChats;
        }

        @Override
        public JsonNode digestInput(ReadRequest request) {
            var node = JSON.createObjectNode();
            node.put("conversation_kind", request.kind().wireValue());
            node.put("conversation_id", Long.toString(request.conversationId()));
            node.put("displayed_seq", request.displayedSeq());
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, ReadRequest request) {
            return new LockPlan(Map.of(), Set.of(conversationKey(request.kind(), request.conversationId())));
        }

        @Override
        public ReadRequest qualify(ExecutionContext context, ReadRequest request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, ReadRequest request, ResourceRef resource) {
            if (!request.kind().wireValue().equals(resource.type()) || resource.id() != request.conversationId()) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "会话不存在");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, ReadRequest request,
                                             ReadRequest qualification, LockPlan plan) {
            ConversationViews.ReadProgress progress = request.kind() == ConversationKind.CHAT
                    ? conversations.advanceChatRead(transaction, transaction.context(), request.conversationId(),
                    request.displayedSeq())
                    : tradeChats.advanceRead(transaction, transaction.context(), request.conversationId(),
                    request.displayedSeq());
            BusinessEventIntents.messageRead(transaction, realtimeReference(request.kind(), request.conversationId()),
                    progress.lastReadSeq(), "message_read:" + transaction.operationId());
            return new WriteResult.Response<>(200, ConversationWire.read(progress),
                    new ResourceRef(request.kind().wireValue(), request.conversationId()));
        }
    }

    private static RealtimeEventSources.ConversationRef realtimeReference(ConversationKind kind, long id) {
        return new RealtimeEventSources.ConversationRef(RealtimeEventSources.ConversationKind.valueOf(kind.name()), id);
    }

    private static final class CaseReadUseCase implements WriteExecutor.UseCase<CaseReadRequest, CaseReadRequest> {
        private final CaseConversations cases;

        private CaseReadUseCase(CaseConversations cases) {
            this.cases = cases;
        }

        @Override
        public JsonNode digestInput(CaseReadRequest request) {
            var node = JSON.createObjectNode();
            node.put("conversation_id", Long.toString(request.conversationId()));
            node.put("displayed_seq", request.displayedSeq());
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, CaseReadRequest request) {
            return new LockPlan(Map.of(), Set.of(
                    new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION, List.of(request.conversationId()))));
        }

        @Override
        public CaseReadRequest qualify(ExecutionContext context, CaseReadRequest request, LockPlan plan) {
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, CaseReadRequest request, ResourceRef resource) {
            if (!"case_conversation".equals(resource.type()) || resource.id() != request.conversationId()) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "会话不存在");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, CaseReadRequest request,
                                             CaseReadRequest qualification, LockPlan plan) {
            var progress = cases.advanceRead(transaction, request.conversationId(),
                    Long.parseLong(transaction.context().actorId()), request.displayedSeq());
            var body = ConversationWire.read(new ConversationViews.ReadProgress(progress.lastReadSeq(),
                    progress.unreadCount(), progress.updatedAt()));
            return new WriteResult.Response<>(200, body,
                    new ResourceRef("case_conversation", request.conversationId()));
        }

    }

    private static LockPlan.Key conversationKey(ConversationKind kind, long conversationId) {
        var domain = switch (kind) {
            case CHAT -> LockPlan.Domain.CHAT_CONVERSATION;
            case TRADE -> LockPlan.Domain.TRADE_CONVERSATION;
            case CASE -> LockPlan.Domain.CASE_CONVERSATION;
        };
        return new LockPlan.Key(domain, List.of(conversationId));
    }
}
