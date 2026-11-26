package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.account.application.AccountQueries;
import io.github.iy88.project1.account.application.AccountRestrictions;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.casemanagement.CaseSettings;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CaseApplication;
import io.github.iy88.project1.casemanagement.application.CaseCommands;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseQueries;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.conversation.CaseMessageKind;
import io.github.iy88.project1.conversation.MessageSenderKind;
import io.github.iy88.project1.conversation.application.CaseParticipation;
import io.github.iy88.project1.conversation.persistence.CaseMessage;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.product.application.ProductDisplayRestrictions;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradeReviewReadModel;
import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.OptionalLong;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import tools.jackson.databind.json.JsonMapper;

/**
 * Wires the case lifecycle onto the shared write executor and adapts the account, product, trade,
 * conversation, file and notification modules. Missing optional enforcement support fails the
 * decision instead of recording an execution that did not happen.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
public class CaseHttpConfiguration {
    private static final String MANAGER_ROLE = "manager";

    @Bean
    CasePorts.Targets caseTargets(ProductRepository products, AccountRepository accounts,
                                  ConversationReader reader, ConversationStore conversations,
                                  TradePorts.Participation trades, ProductInteractions comments,
                                  TradeReviewReadModel reviews) {
        return new CaseTargetAdapter(products, accounts, reader, conversations, trades, comments, reviews);
    }

    @Bean
    CasePorts.Managers caseManagers(AccountRepository accounts) {
        return new CaseManagerAdapter(accounts);
    }

    @Bean
    CasePorts.Accounts caseAccounts(AccountRepository accounts, AccountQueries queries) {
        return new CasePorts.Accounts() {
            @Override
            public boolean exists(long accountId) {
                return accounts.findById(accountId).isPresent();
            }

            @Override
            public boolean writeRestricted(long accountId) {
                return queries.writeRestricted(accountId);
            }
        };
    }

    @Bean
    CasePorts.Notifications caseNotifications(NotificationApplication notifications) {
        return new CaseNotificationAdapter(notifications);
    }

    @Bean
    CasePorts.Threads caseThreads(ConversationStore conversations) {
        return new CaseThreadAdapter(conversations);
    }

    @Bean
    CasePorts.EvidenceFiles caseEvidenceFiles(FileReferences files) {
        return new CaseEvidenceAdapter(files);
    }

    @Bean
    CasePorts.Enforcement caseEnforcement(CaseLifecycleStore cases, CasePorts.Targets targets,
                                          AccountRestrictions accounts, ProductDisplayRestrictions displays,
                                          ProductRepository products, ProductInteractions comments,
                                          TradePorts.Closure closures, TradePorts.CaseEnforcement trades,
                                          TradePorts.Participation participation, ObjectProvider<Clock> clocks) {
        var tradeHandler = new TradeCaseEnforcement(trades, participation);
        var subjectHandler = new SubjectCaseEnforcement(cases, targets, accounts, displays, products, comments,
                closures, trades, participation, clocks.getIfAvailable(Clock::systemUTC));
        return new CoordinatingCaseEnforcement(tradeHandler, subjectHandler);
    }

    @Bean
    CaseApplication caseApplication(WriteExecutor writes, CaseLifecycleStore store, CasePorts.Targets targets,
                                    CasePorts.Managers managers, CasePorts.Accounts accounts,
                                    CasePorts.Notifications notifications, CasePorts.Threads threads,
                                    CasePorts.EvidenceFiles files, CasePorts.Enforcement enforcement,
                                    CaseSettings settings, JsonMapper json, ObjectProvider<Clock> clocks) {
        return new CaseApplication(writes, store, targets, managers, accounts, notifications, threads, files,
                enforcement, settings, json, clocks.getIfAvailable(Clock::systemUTC));
    }

    @Bean
    CaseQueries caseQueries(org.springframework.jdbc.core.simple.JdbcClient jdbc, CaseLifecycleStore store,
                            CasePorts.Threads threads, CasePorts.Managers managers, CaseSettings settings,
                            JsonMapper json, ObjectProvider<Clock> clocks) {
        return new CaseQueries(jdbc, store, threads, managers, settings, json,
                clocks.getIfAvailable(Clock::systemUTC));
    }

    @Bean
    CaseParticipation caseParticipation(CaseLifecycleStore store, AccountRepository accounts) {
        return (caseId, relatedAccountId, actorAccountId) -> {
            if (actorAccountId == relatedAccountId) {
                return true;
            }
            return store.find(caseId)
                    .filter(facts -> facts.claimedBy(actorAccountId))
                    .map(facts -> accounts.findById(actorAccountId))
                    .filter(account -> account.map(CaseHttpConfiguration::manager).orElse(false))
                    .isPresent();
        };
    }

    private static boolean manager(Account account) {
        return MANAGER_ROLE.equals(account.role());
    }

    // ------------------------------------------------------------------ adapters

    private record CaseManagerAdapter(AccountRepository accounts) implements CasePorts.Managers {
        @Override
        public void requireManager(ExecutionContext context) {
            long actor = Long.parseLong(context.actorId());
            var account = accounts.findById(actor)
                    .orElseThrow(CaseManagerAdapter::forbidden);
            if (!manager(account)) {
                throw forbidden();
            }
        }

        @Override
        public void requireManagerForWrite(ExecutionContext context) {
            requireManager(context);
        }

        private static BusinessError forbidden() {
            return new BusinessError("ACTION_NOT_ALLOWED", 403, "当前账户无管理资格");
        }
    }

    private record CaseNotificationAdapter(NotificationApplication notifications)
            implements CasePorts.Notifications {
        private static final String TEMPLATE_VERSION = "1";

        @Override
        public void create(WriteTransaction transaction, String eventType, String intentKey, ResourceRef source,
                           Set<Long> recipients, Map<String, String> params, Instant occurredAt) {
            var intent = new NotificationIntent(recipients, null, eventType, source, intentKey,
                    templateKey(eventType), TEMPLATE_VERSION, params == null ? Map.of() : params, occurredAt);
            notifications.createNotifications(transaction, intent);
        }

        private static String templateKey(String eventType) {
            if (eventType.startsWith("case.trade_")) {
                return "case.enforcement";
            }
            return switch (eventType) {
                case "case.inquiry_created" -> "case.inquiry";
                case "case.appeal_resolved" -> "case.appeal";
                case "case.result_published" -> "case.result";
                default -> "case.decision";
            };
        }
    }

    private record CaseThreadAdapter(ConversationStore conversations) implements CasePorts.Threads {
        @Override
        public long ensure(WriteTransaction transaction, long caseId, long relatedAccountId) {
            return conversations.ensureCase(transaction, caseId, relatedAccountId).id();
        }

        @Override
        public CaseRecords.ThreadMessage append(WriteTransaction transaction, long caseId, long relatedAccountId,
                                                String messageKind, String senderKind, long senderAccountId,
                                                String body) {
            var conversation = conversations.findCase(caseId, relatedAccountId)
                    .orElseThrow(CaseThreadAdapter::participantRequired);
            if (CaseVocabulary.KIND_SYSTEM_NOTICE.equals(messageKind)) {
                var message = conversations.appendCaseSystemEvent(transaction, conversation,
                        UUID.randomUUID(), "case_system_notice", body);
                return message(conversation.id(), message);
            }
            var message = conversations.appendCaseMessage(transaction, conversation, kind(messageKind),
                    sender(senderKind), senderAccountId, body);
            return message(conversation.id(), message);
        }

        @Override
        public boolean archive(WriteTransaction transaction, long caseId, long relatedAccountId) {
            return conversations.findCase(caseId, relatedAccountId)
                    .map(conversation -> conversations.archiveCase(transaction, conversation))
                    .orElse(false);
        }

        @Override
        public OptionalLong findConversation(long caseId, long relatedAccountId) {
            return conversations.findCase(caseId, relatedAccountId)
                    .map(conversation -> OptionalLong.of(conversation.id()))
                    .orElseGet(OptionalLong::empty);
        }

        private static CaseRecords.ThreadMessage message(long conversationId, CaseMessage message) {
            return new CaseRecords.ThreadMessage(conversationId, message.id(), message.seq(), message.createdAt());
        }

        private static CaseMessageKind kind(String value) {
            return switch (value) {
                case CaseVocabulary.KIND_INQUIRY -> CaseMessageKind.INQUIRY;
                case CaseVocabulary.KIND_STATEMENT -> CaseMessageKind.STATEMENT;
                case CaseVocabulary.KIND_APPEAL -> CaseMessageKind.APPEAL;
                case CaseVocabulary.KIND_MANAGER_REPLY -> CaseMessageKind.MANAGER_REPLY;
                default -> throw new BusinessError("INPUT_INVALID", 422, "message_kind 取值无效");
            };
        }

        private static MessageSenderKind sender(String value) {
            return switch (value) {
                case CaseVocabulary.ACTOR_ACCOUNT -> MessageSenderKind.ACCOUNT;
                case CaseVocabulary.ACTOR_MANAGER -> MessageSenderKind.MANAGER;
                default -> throw new BusinessError("INPUT_INVALID", 422, "发送角色无效");
            };
        }

        private static BusinessError participantRequired() {
            return new BusinessError("PARTICIPANT_REQUIRED", 404, "事项线程不存在");
        }
    }

    private record CaseEvidenceAdapter(FileReferences files) implements CasePorts.EvidenceFiles {
        @Override
        public void lockFile(long fileId) {
            try {
                files.lockFiles(List.of(fileId));
            } catch (FileRegistry.Rejected rejected) {
                throw evidenceError(rejected);
            }
        }

        @Override
        public List<Long> attach(WriteTransaction transaction, long caseId, long submitterId, List<Long> fileIds) {
            var target = new UploadRegistration.Target("case", caseId);
            try {
                return files.attach(submitterId, target, FilePurpose.CASE_EVIDENCE, fileIds, "evidence").stream()
                        .map(FileReferences.Reference::referenceId).toList();
            } catch (FileRegistry.Rejected rejected) {
                throw evidenceError(rejected);
            }
        }

        /**
         * Maps the shared file rejections onto the case evidence contract: a missing or foreign
         * file stays hidden, while an unverified or wrong-purpose file is evidence out of scope.
         */
        private static BusinessError evidenceError(FileRegistry.Rejected rejected) {
            String code = rejected.getMessage();
            if ("RESOURCE_NOT_VISIBLE".equals(code)) {
                return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "文件不可见");
            }
            return new BusinessError("EVIDENCE_OUT_OF_SCOPE", 422, "证据文件不可引用");
        }
    }

    // ------------------------------------------------------------------ target projection

    private record CaseTargetAdapter(ProductRepository products, AccountRepository accounts,
                                     ConversationReader reader, ConversationStore conversations,
                                     TradePorts.Participation trades, ProductInteractions comments,
                                     TradeReviewReadModel reviews) implements CasePorts.Targets {
        @Override
        public void requireReportable(CaseCommands.Target target, long reporterAccountId) {
            switch (target.targetType()) {
                case "product" -> {
                    var product = products.findById(target.targetId())
                            .orElseThrow(CaseTargetAdapter::targetInvalid);
                    if (product.sellerAccountId() == reporterAccountId) {
                        throw targetInvalid();
                    }
                }
                case "account" -> {
                    accounts.findById(target.targetId()).orElseThrow(CaseTargetAdapter::targetInvalid);
                    if (target.targetId() == reporterAccountId) {
                        throw targetInvalid();
                    }
                }
                case "trade" -> {
                    var access = trades.findConversationAccess(target.targetId())
                            .orElseThrow(CaseTargetAdapter::targetInvalid);
                    if (access.buyerId() != reporterAccountId && access.sellerId() != reporterAccountId) {
                        throw targetInvalid();
                    }
                }
                case "comment" -> comments.reportableCommentAuthor(reporterAccountId, target.targetId())
                        .orElseThrow(CaseTargetAdapter::targetInvalid);
                case "evaluation" -> reviews.reportableReviewAuthor(reporterAccountId, target.targetId())
                        .orElseThrow(CaseTargetAdapter::targetInvalid);
                case "message" -> requireMessageTarget(target, reporterAccountId);
                default -> throw targetInvalid();
            }
        }

        @Override
        public Set<Long> relatedAccountIds(CaseRecords.Facts facts) {
            if (facts.targetId() == null) {
                return Set.of();
            }
            return switch (facts.targetType()) {
                case "product" -> products.findById(facts.targetId())
                        .map(product -> Set.of(product.sellerAccountId())).orElse(Set.of());
                case "account" -> Set.of(facts.targetId());
                case "comment" -> comments.commentAuthor(facts.targetId()).map(Set::of).orElse(Set.of());
                case "evaluation" -> reviews.reviewAuthor(facts.targetId()).map(Set::of).orElse(Set.of());
                case "trade" -> tradeParties(facts.targetId());
                case "message" -> messageParticipants(facts.conversationKind(), facts.conversationId());
                default -> Set.of();
            };
        }

        @Override
        public Set<Long> tradeParties(long tradeId) {
            var access = trades.findConversationAccess(tradeId);
            if (access.isEmpty()) {
                return Set.of();
            }
            return new TreeSet<>(List.of(access.get().buyerId(), access.get().sellerId()));
        }

        private void requireMessageTarget(CaseCommands.Target target, long reporterAccountId) {
            String kind = target.conversationKind();
            long conversationId = target.conversationId();
            boolean participant = switch (kind) {
                case "chat" -> {
                    var message = reader.findChatMessage(conversationId, target.targetId())
                            .orElseThrow(CaseTargetAdapter::targetInvalid);
                    if (message.senderAccountId() == reporterAccountId) {
                        throw targetInvalid();
                    }
                    yield conversations.chat(conversationId).involves(reporterAccountId);
                }
                case "trade" -> {
                    var message = reader.findTradeMessage(conversationId, target.targetId())
                            .orElseThrow(CaseTargetAdapter::targetInvalid);
                    if (Objects.equals(message.senderAccountId(), reporterAccountId)) {
                        throw targetInvalid();
                    }
                    var parties = tradeParties(conversations.trade(conversationId).tradeId());
                    yield parties.contains(reporterAccountId);
                }
                case "case" -> {
                    var message = reader.findCaseMessage(conversationId, target.targetId())
                            .orElseThrow(CaseTargetAdapter::targetInvalid);
                    if (Objects.equals(message.senderAccountId(), reporterAccountId)) {
                        throw targetInvalid();
                    }
                    yield conversations.caseConversation(conversationId).relatedAccountId() == reporterAccountId;
                }
                default -> false;
            };
            if (!participant) {
                throw targetInvalid();
            }
        }

        private Set<Long> messageParticipants(String conversationKind, Long conversationId) {
            if (conversationKind == null || conversationId == null) {
                return Set.of();
            }
            return switch (conversationKind) {
                case "chat" -> {
                    var conversation = conversations.chat(conversationId);
                    yield Set.of(conversation.accountLowId(), conversation.accountHighId());
                }
                case "trade" -> tradeParties(conversations.trade(conversationId).tradeId());
                case "case" -> Set.of(conversations.caseConversation(conversationId).relatedAccountId());
                default -> Set.of();
            };
        }

        private static BusinessError targetInvalid() {
            return new BusinessError("TARGET_INVALID", 422, "举报对象无效");
        }
    }
}
