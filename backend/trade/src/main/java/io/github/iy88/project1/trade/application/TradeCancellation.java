package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.CancellationMode;
import io.github.iy88.project1.trade.domain.TradeVocabulary.CancellationStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.Decision;
import io.github.iy88.project1.trade.domain.TradeVocabulary.TerminalReason;
import io.github.iy88.project1.trade.domain.TradeVocabulary.WaitEndReason;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.util.Set;
import java.util.UUID;
import tools.jackson.databind.json.JsonMapper;

/** Negotiated and direct cancellation write workflows, owned by the trade module. */
final class TradeCancellation {
    private final TradeRepository repository;
    private final TradeHistoryWriter historyWriter;
    private final TradeViews views;
    private final TradeQueries queries;
    private final TradePorts.Accounts accounts;
    private final TradePorts.Conversation conversations;
    private final TradePorts.Notifications notifications;
    private final TradePorts.Product product;
    private final Clock clock;
    private final JsonMapper json;

    TradeCancellation(TradeRepository repository, TradeHistoryWriter historyWriter, TradeViews views,
                      TradeQueries queries, TradePorts.Accounts accounts, TradePorts.Conversation conversations,
                      TradePorts.Notifications notifications, TradePorts.Product product, Clock clock,
                      JsonMapper json) {
        this.repository = repository;
        this.historyWriter = historyWriter;
        this.views = views;
        this.queries = queries;
        this.accounts = accounts;
        this.conversations = conversations;
        this.notifications = notifications;
        this.product = product;
        this.clock = clock;
        this.json = json;
    }

    WriteResult.Response<?> propose(WriteTransaction transaction, long actor,
                                    TradeCommands.ProposeCancellation request) {
        String reason = TradeWriteSupport.optionalText(request.reason(), 500, "取消原因");
        var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
        TradeWriteSupport.requireWrite(accounts, actor);
        var state = TradeWriteSupport.lockProduct(product, transaction, pre.productId());
        var trade = repository.lockTrade(transaction, request.tradeId());
        trade.requireNotTerminal();
        requireCancellable(trade);
        TradeWriteSupport.requireNotFrozen(repository, trade.id());
        trade.requireVersion(request.expectedVersion());
        long conversationId = TradeWriteSupport.requireConversation(transaction, conversations, queries, trade.id());
        if (repository.pendingCancellation(trade.id()).isPresent()) {
            throw new BusinessError("CANCELLATION_ALREADY_PENDING", 409, "已有待决取消申请");
        }
        var now = TradeWriteSupport.now(clock, repository);
        boolean direct = trade.cancellationMode(actor,
                !repository.currentConfirmations(trade.id()).isEmpty()) == CancellationMode.DIRECT;
        UUID requestEvent = UUID.randomUUID();
        var proposal = new TradeModels.Cancellation(0, trade.id(), actor,
                direct ? CancellationMode.DIRECT : CancellationMode.APPROVAL, reason,
                direct ? CancellationStatus.ACCEPTED : CancellationStatus.PENDING, now, requestEvent);
        long proposalId = repository.insertCancellation(proposal);
        proposal = withId(proposal, proposalId);
        if (direct) {
            UUID decisionEvent = UUID.randomUUID();
            var decision = new TradeModels.CancellationDecision(0, proposalId, Decision.ACCEPT, actor, now,
                    decisionEvent);
            long decisionId = repository.insertCancellationDecision(decision);
            var terminated = TradeWriteSupport.changed(trade, TradeStatus.TERMINATED, trade.activeAgreementId(),
                    null, TerminalReason.CANCELLED.value(), trade.respondedAt(), now, now);
            repository.save(terminated);
            TradeWriteSupport.endWait(repository, trade.id(), WaitEndReason.TERMINATED, now);
            repository.endAllFreezes(trade.id(), now);
            repository.terminateOpenDisputes(trade.id(), now);
            product.releaseToPublic(transaction, state, trade.id(), "cancelled");
            historyWriter.historyCancellation(transaction,
                    trade, terminated, "cancellation.request", trade.actorKind(actor),
                    actor, reason, null, null, proposalId, null, requestEvent, now);
            conversations.append(transaction, conversationId, requestEvent, "cancellation_requested",
                    "买方直接取消了交易", new ResourceRef("cancellation_request", proposalId));
            historyWriter.historyCancellation(transaction,
                    trade, terminated, "cancellation.accept", ActorKind.BUYER, actor,
                    reason, null, null, proposalId, decisionId, decisionEvent, now);
            conversations.append(transaction, conversationId, decisionEvent, "cancellation_accepted",
                    "交易已终止", new ResourceRef("cancellation_decision", decisionId));
            UUID terminatedEvent = UUID.randomUUID();
            long terminatedHistory = historyWriter.historyCancellation(transaction,
                    trade, terminated, "trade.terminated",
                    ActorKind.SYSTEM, null, reason, null, null, proposalId, decisionId, terminatedEvent, now);
            conversations.append(transaction, conversationId, terminatedEvent, "trade_terminated",
                    "交易已终止，商品仍保持上架。", new ResourceRef("trade_transition", terminatedHistory));
            notifications.register(transaction, terminatedEvent, "trade.terminated", trade.id(),
                    Set.of(trade.buyerId(), trade.sellerId()));
            conversations.archive(transaction, conversationId, trade.id(), "cancelled");
        } else {
            var updated = TradeWriteSupport.changed(trade, trade.status(), trade.activeAgreementId(),
                    trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
            repository.save(updated);
            historyWriter.historyCancellation(transaction,
                    trade, updated, "cancellation.request", trade.actorKind(actor),
                    actor, reason, null, null, proposalId, null, requestEvent, now);
            conversations.append(transaction, conversationId, requestEvent, "cancellation_requested",
                    "取消申请已提交", new ResourceRef("cancellation_request", proposalId));
            notifications.register(transaction, requestEvent, "trade.cancellation_requested", trade.id(),
                    Set.of(TradeWriteSupport.other(trade, actor)));
        }
        TradeWriteSupport.audit(json, transaction, "trade.cancellation.propose", trade.id(), null);
        var body = json.createObjectNode();
        body.put("mode", proposal.mode().value());
        body.set("proposal", views.cancellationRecord(proposal));
        body.set("trade", queries.view(trade.id(), actor, conversationId));
        return new WriteResult.Response<>(201, body, new ResourceRef("trade", trade.id()));
    }

    WriteResult.Response<?> decide(WriteTransaction transaction, long actor,
                                   TradeCommands.DecideCancellation request) {
        Decision decision = TradeWriteSupport.decision(request.decision());
        var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
        TradeWriteSupport.requireWrite(accounts, actor);
        var state = TradeWriteSupport.lockProduct(product, transaction, pre.productId());
        var trade = repository.lockTrade(transaction, request.tradeId());
        trade.requireNotTerminal();
        requireCancellable(trade);
        TradeWriteSupport.requireNotFrozen(repository, trade.id());
        trade.requireVersion(request.expectedVersion());
        long conversationId = TradeWriteSupport.requireConversation(transaction, conversations, queries, trade.id());
        var proposal = repository.cancellation(request.cancellationId())
                .orElseThrow(() -> new BusinessError("CANCELLATION_NOT_PENDING", 409, "取消申请不存在"));
        if (proposal.tradeId() != trade.id() || proposal.status() != CancellationStatus.PENDING) {
            throw new BusinessError("CANCELLATION_NOT_PENDING", 409, "取消申请已决或不属于本交易");
        }
        if (decision == Decision.WITHDRAW) {
            if (proposal.proposedBy() != actor) {
                throw Trade.actionNotAllowed();
            }
        } else if (proposal.proposedBy() == actor) {
            throw Trade.actionNotAllowed();
        }
        var now = TradeWriteSupport.now(clock, repository);
        UUID decisionEvent = UUID.randomUUID();
        var stored = new TradeModels.CancellationDecision(0, proposal.id(), decision, actor, now, decisionEvent);
        long decisionId = repository.insertCancellationDecision(stored);
        if (decision == Decision.ACCEPT) {
            repository.setCancellationStatus(proposal.id(), CancellationStatus.ACCEPTED);
            var terminated = TradeWriteSupport.changed(trade, TradeStatus.TERMINATED, trade.activeAgreementId(),
                    null, TerminalReason.CANCELLED.value(), trade.respondedAt(), now, now);
            repository.save(terminated);
            TradeWriteSupport.endWait(repository, trade.id(), WaitEndReason.TERMINATED, now);
            repository.endAllFreezes(trade.id(), now);
            repository.terminateOpenDisputes(trade.id(), now);
            product.releaseToPublic(transaction, state, trade.id(), "cancelled");
            historyWriter.historyCancellation(transaction,
                    trade, terminated, "cancellation.accept", trade.actorKind(actor),
                    actor, null, null, null, proposal.id(), decisionId, decisionEvent, now);
            conversations.append(transaction, conversationId, decisionEvent, "cancellation_accepted",
                    "取消申请已同意，交易终止", new ResourceRef("cancellation_decision", decisionId));
            UUID terminatedEvent = UUID.randomUUID();
            long terminatedHistory = historyWriter.historyCancellation(transaction,
                    trade, terminated, "trade.terminated",
                    ActorKind.SYSTEM, null, null, null, null, proposal.id(), decisionId, terminatedEvent, now);
            conversations.append(transaction, conversationId, terminatedEvent, "trade_terminated",
                    "交易已终止，商品仍保持上架。", new ResourceRef("trade_transition", terminatedHistory));
            notifications.register(transaction, terminatedEvent, "trade.terminated", trade.id(),
                    Set.of(trade.buyerId(), trade.sellerId()));
            conversations.archive(transaction, conversationId, trade.id(), "cancelled");
        } else {
            repository.setCancellationStatus(proposal.id(),
                    decision == Decision.REJECT ? CancellationStatus.REJECTED : CancellationStatus.WITHDRAWN);
            var updated = TradeWriteSupport.changed(trade, trade.status(), trade.activeAgreementId(),
                    trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
            repository.save(updated);
            String action = decision == Decision.REJECT ? "cancellation.reject" : "cancellation.withdraw";
            historyWriter.historyCancellation(transaction,
                    trade, updated, action, trade.actorKind(actor), actor, null, null,
                    null, proposal.id(), decisionId, decisionEvent, now);
            String type = decision == Decision.REJECT ? "cancellation_rejected" : "cancellation_withdrawn";
            conversations.append(transaction, conversationId, decisionEvent, type,
                    decision == Decision.REJECT ? "取消申请被拒绝" : "取消申请已撤回",
                    new ResourceRef("cancellation_decision", decisionId));
            notifications.register(transaction, decisionEvent, "trade." + type, trade.id(),
                    Set.of(TradeWriteSupport.other(trade, actor)));
        }
        TradeWriteSupport.audit(json, transaction, "trade.cancellation." + decision.value(), trade.id(), null);
        var updatedProposal = repository.cancellation(proposal.id()).orElseThrow();
        var body = json.createObjectNode();
        body.set("proposal", views.cancellationRecord(updatedProposal));
        body.set("trade", queries.view(trade.id(), actor, conversationId));
        return new WriteResult.Response<>(200, body, new ResourceRef("trade", trade.id()));
    }

    private static void requireCancellable(Trade trade) {
        if (trade.status() == TradeStatus.ABNORMAL) {
            throw new BusinessError("STATE_CONFLICT", 409, "异常交易需管理员处理");
        }
        if (trade.status() != TradeStatus.IN_PROGRESS && trade.status() != TradeStatus.DISPUTED) {
            throw Trade.stateConflict();
        }
    }

    private static TradeModels.Cancellation withId(TradeModels.Cancellation cancellation, long id) {
        return new TradeModels.Cancellation(id, cancellation.tradeId(), cancellation.proposedBy(),
                cancellation.mode(), cancellation.reason(), cancellation.status(), cancellation.proposedAt(),
                cancellation.businessEventId());
    }
}
