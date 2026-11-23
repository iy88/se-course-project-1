package io.github.iy88.project1.api.conversation;

import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.conversation.application.AccountDirectory;
import io.github.iy88.project1.conversation.application.CaseConversations;
import io.github.iy88.project1.conversation.application.ConversationQueries;
import io.github.iy88.project1.conversation.application.Conversations;
import io.github.iy88.project1.conversation.application.TradeChats;
import io.github.iy88.project1.conversation.application.TradeParticipation;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.WriteExecutor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Wires the conversation ports and write commands for normal process roles. Diagnostic probes and
 * lightweight MVC slices run without these beans, which is why the controller answers 503 instead
 * of failing startup.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class ConversationHttpConfiguration {

    @Bean
    AccountDirectory conversationAccountDirectory(AccountQueries accounts) {
        return new ConversationAccountDirectory(accounts);
    }

    @Bean
    ConversationWriteCommands conversationWriteCommands(WriteExecutor writes, Conversations conversations,
                                                        TradeChats tradeChats, ConversationStore store,
                                                        TradeParticipation trades,
                                                        CaseConversations caseConversations) {
        return new WriteBackedConversationCommands(writes, conversations, tradeChats, store, trades,
                caseConversations);
    }
}
