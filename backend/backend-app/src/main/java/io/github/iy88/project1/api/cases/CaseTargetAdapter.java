package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.account.persistence.AccountRepository;
import io.github.iy88.project1.casemanagement.application.CaseCommands;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.conversation.persistence.ConversationReader;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.application.ProductService;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradeReviewModeration;
import io.github.iy88.project1.trade.application.TradeReviewReadModel;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.TreeSet;

/**
 * Projects case targets, dispositions and reported messages onto the account, product, trade,
 * conversation and review modules.
 */
record CaseTargetAdapter(ProductRepository products, AccountRepository accounts,
                         ConversationReader reader, ConversationStore conversations,
                         TradePorts.Participation trades, ProductInteractions comments,
                         TradeReviewReadModel reviews, TradeReviewModeration moderation,
                         ProductService productService) implements CasePorts.Targets {
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
                if (target.targetId() == reporterAccountId || (target.sourceProductId() != null
                        && (!productService.ownsProduct(target.targetId(), target.sourceProductId())
                        || productService.notificationTitle(reporterAccountId, target.sourceProductId()).isEmpty()))) {
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
    public void captureReportSnapshot(long caseId, CaseCommands.Target target) {
        if ("product".equals(target.targetType())) {
            productService.captureReportSnapshot(caseId, target.targetId());
        } else if (target.sourceProductId() != null) {
            productService.captureReportSnapshot(caseId, target.sourceProductId());
        }
    }

    @Override
    public Optional<CasePorts.Targets.TargetSnapshot> contentTarget(CaseRecords.Facts facts) {
        if (facts.targetId() == null) {
            return Optional.empty();
        }
        return switch (facts.targetType() == null ? "" : facts.targetType()) {
            case "comment" -> comments.commentSnapshot(facts.targetId())
                    .map(fact -> new CasePorts.Targets.TargetSnapshot("comment", fact.commentId(),
                            fact.authorAccountId(), fact.parentCommentId(), fact.productId(), fact.body(), fact.state(),
                            fact.createdAt(), fact.removedAt() != null));
            case "evaluation" -> moderation.snapshot(facts.targetId())
                    .map(fact -> new CasePorts.Targets.TargetSnapshot("evaluation", fact.reviewId(),
                            fact.authorAccountId(), null, fact.tradeId(), fact.body(), fact.state(),
                            fact.createdAt(), fact.removedAt() != null));
            default -> Optional.empty();
        };
    }

    @Override
    public java.util.Map<Long, String> accountNames(Set<Long> ids) {
        return accounts.findByIdIn(ids).stream().collect(java.util.stream.Collectors.toMap(
                account -> account.id(), account -> account.displayName()));
    }

    @Override
    public Optional<ReportProduct> reportProduct(long caseId) {
        return productService.reportSnapshot(caseId)
                .map(item -> new ReportProduct(item.id(), item.title(), item.description()));
    }

    @Override
    public List<DispositionProduct> dispositionProducts(CaseRecords.Facts facts) {
        if (facts.targetId() == null) {
            return List.of();
        }
        if ("account".equals(facts.targetType())) {
            return products.findForSeller(facts.targetId(), null, org.springframework.data.domain.Pageable.unpaged())
                    .map(product -> new DispositionProduct(product.id(), product.title()))
                    .getContent();
        }
        Optional<Long> productId = switch (facts.targetType()) {
            case "product" -> Optional.of(facts.targetId());
            case "comment" -> comments.commentSnapshot(facts.targetId()).map(item -> item.productId());
            case "trade" -> trades.productId(facts.targetId()).stream().boxed().findFirst();
            default -> Optional.empty();
        };
        return productId.flatMap(products::findById).filter(product -> !product.deleted())
                .map(product -> new DispositionProduct(product.id(), product.title())).stream().toList();
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

    @Override
    public CaseRecords.ReferencedMessage requireReportedMessage(CaseRecords.Facts facts, String conversationKind,
                                                                long conversationId, long messageId) {
        if (!"message".equals(facts.targetType()) || facts.targetId() == null
                || facts.targetId() != messageId
                || !Objects.equals(facts.conversationKind(), conversationKind)
                || facts.conversationId() == null || facts.conversationId() != conversationId) {
            throw evidenceOutOfScope();
        }
        return switch (conversationKind) {
            case "chat" -> reader.findChatMessage(conversationId, messageId)
                    .map(message -> new CaseRecords.ReferencedMessage(message.id(), "chat",
                            message.conversationId(), "account", message.senderAccountId(),
                            message.body(), message.createdAt()))
                    .orElseThrow(CaseTargetAdapter::evidenceOutOfScope);
            case "trade" -> reader.findTradeMessage(conversationId, messageId)
                    .map(message -> new CaseRecords.ReferencedMessage(message.id(), "trade",
                            message.conversationId(), message.senderKind(), message.senderAccountId(),
                            message.body(), message.createdAt()))
                    .orElseThrow(CaseTargetAdapter::evidenceOutOfScope);
            case "case" -> reader.findCaseMessage(conversationId, messageId)
                    .map(message -> new CaseRecords.ReferencedMessage(message.id(), "case",
                            message.conversationId(), message.senderKind(), message.senderAccountId(),
                            message.body(), message.createdAt()))
                    .orElseThrow(CaseTargetAdapter::evidenceOutOfScope);
            default -> throw evidenceOutOfScope();
        };
    }

    private static BusinessError evidenceOutOfScope() {
        return new BusinessError("EVIDENCE_OUT_OF_SCOPE", 422, "证据引用不在事项范围内");
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
