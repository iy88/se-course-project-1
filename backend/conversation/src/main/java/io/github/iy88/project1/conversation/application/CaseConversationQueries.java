package io.github.iy88.project1.conversation.application;

import io.github.iy88.project1.conversation.ConversationSettings;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.util.HashSet;
import java.util.Map;
import org.springframework.context.annotation.Lazy;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

/** Read-only case-thread query; access is delegated to the case module's thread qualification rules. */
@Lazy
@Service
@Profile("infrastructure")
public class CaseConversationQueries {
    private final ConversationStore store;
    private final ConversationReader reader;
    private final AccountDirectory accounts;
    private final CaseParticipation cases;
    private final ConversationSettings settings;

    public CaseConversationQueries(ConversationStore store, ConversationReader reader, AccountDirectory accounts,
                                   CaseParticipation cases, ConversationSettings settings) {
        this.store = store;
        this.reader = reader;
        this.accounts = accounts;
        this.cases = cases;
        this.settings = settings;
    }

    public ConversationViews.MessagePage pageCase(ExecutionContext context, long conversationId, Long beforeSeq,
                                                  Long afterSeq, int limit) {
        long actor = accountId(context);
        var conversation = store.caseConversation(conversationId);
        if (!cases.canAccess(conversation.caseId(), conversation.relatedAccountId(), actor)) {
            throw participantRequired();
        }
        if (beforeSeq != null && afterSeq != null) {
            throw new BusinessError("INPUT_INVALID", 422, "before_seq 与 after_seq 只能二选一");
        }
        var messages = reader.caseMessages(conversationId, beforeSeq, afterSeq, pageSize(limit));
        var senderIds = new HashSet<Long>();
        for (CaseMessage message : messages) {
            if (message.senderAccountId() != null) {
                senderIds.add(message.senderAccountId());
            }
        }
        var profiles = accounts.profiles(senderIds);
        var items = messages.stream().map(message -> caseMessage(message, profiles)).toList();
        return new ConversationViews.MessagePage(items,
                items.isEmpty() ? null : items.getLast().seq(),
                items.isEmpty() ? null : items.getFirst().seq(),
                conversation.archived() ? "archived" : "active");
    }

    private ConversationViews.Message caseMessage(CaseMessage message,
                                                  Map<Long, AccountDirectory.Profile> profiles) {
        var senderKind = message.senderKind();
        ConversationViews.Sender sender;
        if ("system".equals(senderKind)) {
            sender = new ConversationViews.Sender(null, "系统", "system");
        } else if ("manager".equals(senderKind)) {
            sender = new ConversationViews.Sender(message.senderAccountId(), "管理员", "manager");
        } else {
            sender = new ConversationViews.Sender(message.senderAccountId(),
                    displayName(message.senderAccountId(), profiles), "account");
        }
        return new ConversationViews.Message(message.id(), message.seq(), sender, message.messageKind(),
                message.body(), message.createdAt(), message.eventType(), null);
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

    private static long accountId(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "需要登录账户");
        }
        return Long.parseLong(context.actorId());
    }

    private static BusinessError participantRequired() {
        return new BusinessError("PARTICIPANT_REQUIRED", 404, "会话不存在或无权访问");
    }
}
