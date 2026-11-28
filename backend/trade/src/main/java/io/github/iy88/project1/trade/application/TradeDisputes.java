package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.DisputeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.InvalidationReason;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ResolutionMode;
import io.github.iy88.project1.trade.domain.TradeVocabulary.WaitEndReason;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.util.UUID;
import tools.jackson.databind.json.JsonMapper;

/** User-side dispute opening and self-resolution confirmation, owned by the trade module. */
final class TradeDisputes {
    private final TradeRepository repository;
    private final TradeHistoryWriter historyWriter;
    private final TradeViews views;
    private final TradeQueries queries;
    private final TradePorts.Accounts accounts;
    private final TradePorts.Conversation conversations;
    private final TradePorts.Cases cases;
    private final Clock clock;
    private final JsonMapper json;

    TradeDisputes(TradeRepository repository, TradeHistoryWriter historyWriter, TradeViews views,
                  TradeQueries queries, TradePorts.Accounts accounts, TradePorts.Conversation conversations,
                  TradePorts.Cases cases, Clock clock, JsonMapper json) {
        this.repository = repository;
        this.historyWriter = historyWriter;
        this.views = views;
        this.queries = queries;
        this.accounts = accounts;
        this.conversations = conversations;
        this.cases = cases;
        this.clock = clock;
        this.json = json;
    }

    /**
     * Keeps the original trade and account plan and adds only the dispute case's own keys. A
     * historical dispute without a case is left as-is: prepare must stay replayable and must not
     * create a case outside the dispute-opening transaction.
     */
    LockPlan prepareConfirmResolution(long actor, long tradeId, long disputeId) {
        var plan = TradeWriteSupport.prepareTrade(repository, conversations, actor, tradeId, false, null);
        var dispute = repository.dispute(disputeId).orElse(null);
        if (dispute == null || dispute.tradeId() != tradeId || dispute.caseId() == null) {
            return plan;
        }
        LockPlan casePlan = cases.prepareSelfResolution(dispute.caseId());
        return casePlan == null ? plan : plan.merge(casePlan);
    }

    WriteResult.Response<?> openDispute(ExecutionContext context, WriteTransaction transaction,
                                        TradeCommands.OpenDispute request) {
        long actor = TradeWriteSupport.actor(context);
        String statement = TradeWriteSupport.requiredText(request.statement(), 2000, "争议说明");
        TradeWriteSupport.requireWrite(accounts, actor);
        var trade = repository.lockTrade(transaction, request.tradeId());
        trade.requireNotTerminal();
        if (trade.status() == TradeStatus.DISPUTED) {
            throw new BusinessError("DISPUTE_ALREADY_OPEN", 409, "已有未解决争议");
        }
        trade.requireInProgress();
        TradeWriteSupport.requireNotFrozen(repository, trade.id());
        trade.requireVersion(request.expectedVersion());
        long conversationId = TradeWriteSupport.requireConversation(transaction, conversations, queries,
                trade.id());
        var now = TradeWriteSupport.now(clock, repository);
        TradeWriteSupport.endWait(repository, trade.id(), WaitEndReason.DISPUTED, now);
        long disputeId = repository.insertDispute(trade.id(), actor, statement, now);
        long caseId = cases.openDisputeCase(transaction, context, trade.id(), disputeId, now);
        repository.attachDisputeCase(disputeId, caseId);
        var dispute = repository.dispute(disputeId).orElseThrow();
        var disputed = TradeWriteSupport.changed(trade, TradeStatus.DISPUTED, trade.activeAgreementId(),
                trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
        repository.save(disputed);
        UUID eventId = UUID.randomUUID();
        long disputeHistory = historyWriter.historyDispute(transaction, trade, disputed, "dispute.open",
                trade.actorKind(actor), actor, statement, null, caseId, disputeId, null, eventId, now);
        conversations.append(transaction, conversationId, eventId, "dispute_opened", "交易争议已发起",
                new ResourceRef("trade_transition", disputeHistory));
        TradeWriteSupport.audit(json, transaction, "trade.dispute.open", trade.id(),
                new ResourceRef("case", caseId));
        var body = json.createObjectNode();
        body.set("dispute", views.disputeRecord(dispute));
        body.set("trade", queries.view(trade.id(), actor, conversationId));
        return new WriteResult.Response<>(201, body, new ResourceRef("trade", trade.id()));
    }

    WriteResult.Response<?> confirmResolution(ExecutionContext context, WriteTransaction transaction,
                                              TradeCommands.ConfirmResolution request) {
        long actor = TradeWriteSupport.actor(context);
        TradeWriteSupport.requireWrite(accounts, actor);
        var trade = repository.lockTrade(transaction, request.tradeId());
        trade.requireParticipant(actor);
        trade.requireNotTerminal();
        if (trade.status() != TradeStatus.DISPUTED) {
            throw new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在");
        }
        TradeWriteSupport.requireNotFrozen(repository, trade.id());
        trade.requireVersion(request.expectedVersion());
        var dispute = repository.dispute(request.disputeId())
                .orElseThrow(() -> new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在"));
        if (dispute.tradeId() != trade.id() || dispute.status() != DisputeStatus.OPEN) {
            throw new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在");
        }
        Long caseId = dispute.caseId();
        if (caseId != null) {
            transaction.lock(TradeWriteSupport.caseKey(caseId),
                    () -> cases.lockSelfResolution(transaction, caseId, trade.id(), dispute.id()));
        }
        long conversationId = TradeWriteSupport.requireConversation(transaction, conversations, queries,
                trade.id());
        var now = TradeWriteSupport.now(clock, repository);
        var existing = repository.resolutionConfirmations(dispute.id()).stream()
                .filter(item -> item.confirmerId() == actor).findFirst();
        if (existing.isPresent()) {
            var body = json.createObjectNode();
            body.set("dispute", views.disputeRecord(dispute));
            body.set("trade", queries.view(trade.id(), actor, conversationId));
            return new WriteResult.Response<>(200, body, new ResourceRef("trade", trade.id()));
        }
        UUID eventId = UUID.randomUUID();
        var confirmation = new TradeModels.ResolutionConfirmation(0, dispute.id(), actor, now, eventId);
        long confirmationId = repository.insertResolutionConfirmation(confirmation);
        var confirmations = repository.resolutionConfirmations(dispute.id());
        if (confirmations.size() >= 2) {
            repository.resolveDispute(dispute.id(), ResolutionMode.SELF, actor, null, now);
            repository.invalidateConfirmations(trade.id(), InvalidationReason.DISPUTE_RESOLVED, now);
            var resolved = TradeWriteSupport.changed(trade, TradeStatus.IN_PROGRESS,
                    trade.activeAgreementId(), trade.closeReason(), trade.terminalReason(),
                    trade.respondedAt(), trade.endedAt(), now);
            repository.save(resolved);
            historyWriter.historyDispute(transaction, trade, resolved, "dispute.resolution_confirm",
                    trade.actorKind(actor), actor, null, null, null, dispute.id(), confirmationId,
                    eventId, now);
            UUID resolvedEvent = UUID.randomUUID();
            long resolvedHistory = historyWriter.historyDispute(transaction,
                    trade, resolved, "dispute.resolve",
                    ActorKind.SYSTEM, null, null, null, null, dispute.id(), confirmationId,
                    resolvedEvent, now);
            conversations.append(transaction, conversationId, resolvedEvent, "dispute_resolved",
                    "双方确认争议已解决，交易恢复进行",
                    new ResourceRef("trade_transition", resolvedHistory));
            if (caseId != null) {
                cases.archiveSelfResolved(transaction, caseId, trade.id(), dispute.id(), now);
            }
        } else {
            var updated = TradeWriteSupport.changed(trade, trade.status(), trade.activeAgreementId(),
                    trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
            repository.save(updated);
            historyWriter.historyDispute(transaction, trade, updated, "dispute.resolution_confirm",
                    trade.actorKind(actor), actor, null, null, null, dispute.id(), confirmationId,
                    eventId, now);
            conversations.append(transaction, conversationId, eventId, "dispute_resolution_confirmed",
                    "一方已确认争议解决", new ResourceRef("dispute_resolution_confirmation",
                            confirmationId));
        }
        TradeWriteSupport.audit(json, transaction, "trade.dispute.resolve", trade.id(), null);
        var body = json.createObjectNode();
        body.set("dispute", views.disputeRecord(repository.dispute(dispute.id()).orElseThrow()));
        body.set("trade", queries.view(trade.id(), actor, conversationId));
        return new WriteResult.Response<>(200, body, new ResourceRef("trade", trade.id()));
    }
}
