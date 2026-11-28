package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.TerminalReason;
import io.github.iy88.project1.trade.domain.TradeVocabulary.WaitEndReason;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.util.Set;
import java.util.UUID;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Completion confirmation write workflow: records one party's confirmation and either starts the
 * confirmation wait or completes the trade, publishing the matching history, conversation and
 * notification facts in the same transaction.
 */
final class TradeConfirmation {
    private final TradeRepository repository;
    private final TradeHistoryWriter historyWriter;
    private final TradeViews views;
    private final TradeQueries queries;
    private final TradePorts.Accounts accounts;
    private final TradePorts.Product product;
    private final TradePorts.Conversation conversations;
    private final TradePorts.Notifications notifications;
    private final TaskSchedules schedules;
    private final TradeSettings settings;
    private final Clock clock;
    private final JsonMapper json;

    TradeConfirmation(TradeRepository repository, TradeHistoryWriter historyWriter, TradeViews views,
                      TradeQueries queries, TradePorts.Accounts accounts, TradePorts.Product product,
                      TradePorts.Conversation conversations, TradePorts.Notifications notifications,
                      TaskSchedules schedules, TradeSettings settings, Clock clock, JsonMapper json) {
        this.repository = repository;
        this.historyWriter = historyWriter;
        this.views = views;
        this.queries = queries;
        this.accounts = accounts;
        this.product = product;
        this.conversations = conversations;
        this.notifications = notifications;
        this.schedules = schedules;
        this.settings = settings;
        this.clock = clock;
        this.json = json;
    }

    WriteResult.Response<?> submit(WriteTransaction transaction, long actor,
                                   TradeCommands.ConfirmCompletion request) {
        String note = TradeWriteSupport.optionalText(request.note(), 1000, "确认说明");
        var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
        TradeWriteSupport.requireWrite(accounts, actor);
        var state = TradeWriteSupport.lockProduct(product, transaction, pre.productId());
        var trade = repository.lockTrade(transaction, request.tradeId());
        trade.requireNotTerminal();
        trade.requireInProgress();
        TradeWriteSupport.requireNotFrozen(repository, trade.id());
        trade.requireVersion(request.expectedVersion());
        long conversationId = TradeWriteSupport.requireConversation(transaction, conversations, queries, trade.id());
        var effective = repository.currentAgreement(trade.id())
                .orElseThrow(() -> new BusinessError("AGREEMENT_REQUIRED", 409, "尚无生效约定"));
        if (trade.activeAgreementId() == null || effective.id() != trade.activeAgreementId()) {
            throw Trade.stateConflict();
        }
        var current = repository.currentConfirmations(trade.id());
        if (current.stream().anyMatch(item -> item.confirmerId() == actor)) {
            throw new BusinessError("CONFIRMATION_ALREADY_SUBMITTED", 409, "本人已提交确认");
        }
        var now = TradeWriteSupport.now(clock, repository);
        var confirmation = new TradeModels.Confirmation(0, trade.id(), effective.id(),
                actor, note, now, null, null, UUID.randomUUID());
        long confirmationId = repository.insertConfirmation(confirmation);
        confirmation = withId(confirmation, confirmationId);
        var counterpart = current.stream()
                .filter(item -> item.confirmerId() == TradeWriteSupport.other(trade, actor))
                .filter(item -> item.agreementId() == effective.id())
                .findFirst();
        if (counterpart.isPresent()) {
            var completed = TradeWriteSupport.changed(trade, TradeStatus.COMPLETED, trade.activeAgreementId(),
                    null, TerminalReason.COMPLETED.value(), trade.respondedAt(), now, now);
            repository.save(completed);
            TradeWriteSupport.endWait(repository, trade.id(), WaitEndReason.COMPLETED, now);
            repository.endAllFreezes(trade.id(), now);
            repository.terminateOpenDisputes(trade.id(), now);
            product.release(transaction, state, trade.id(), "completed");
            UUID confirmationEvent = confirmation.businessEventId();
            historyWriter.historyConfirmation(transaction, trade, completed, "completion.confirm",
                    trade.actorKind(actor), actor, note, null, null, effective.id(), confirmationId,
                    confirmationEvent, now);
            conversations.append(transaction, conversationId, confirmationEvent, "completion_confirmed",
                    "完成确认已提交", new ResourceRef("completion_confirmation", confirmationId));
            UUID completedEvent = UUID.randomUUID();
            long completedHistory = historyWriter.historyConfirmation(transaction, trade, completed,
                    "trade.completed", ActorKind.SYSTEM, null, null, null, null, effective.id(),
                    confirmationId, completedEvent, now);
            conversations.append(transaction, conversationId, completedEvent, "trade_completed",
                    "交易已完成，商品已下架。如需继续出售，可前往商品详情重新上架。",
                    new ResourceRef("trade_transition", completedHistory));
            notifications.register(transaction, completedEvent, "trade.completed", trade.id(),
                    Set.of(trade.buyerId(), trade.sellerId()));
            conversations.archive(transaction, conversationId, trade.id(), "completed");
        } else {
            var updated = TradeWriteSupport.changed(trade, trade.status(), trade.activeAgreementId(),
                    trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
            repository.save(updated);
            var wait = TradeModels.Wait.start(now, settings.confirmationWaitSeconds(), settings.policyVersion());
            repository.saveWait(trade.id(), wait);
            TradeWriteSupport.scheduleTimeout(schedules, trade.id(), wait, now);
            UUID eventId = confirmation.businessEventId();
            historyWriter.historyConfirmation(transaction, trade, updated, "completion.confirm",
                    trade.actorKind(actor), actor, note, null, null, effective.id(), confirmationId,
                    eventId, now);
            conversations.append(transaction, conversationId, eventId, "completion_confirmed",
                    "完成确认已提交，等待对方确认", new ResourceRef("completion_confirmation",
                            confirmationId));
            notifications.register(transaction, eventId, "trade.completion_confirmed", trade.id(),
                    Set.of(TradeWriteSupport.other(trade, actor)));
        }
        TradeWriteSupport.audit(json, transaction, "trade.confirmation.submit", trade.id(), null);
        return new WriteResult.Response<>(201, confirmationEnvelope(confirmation, trade.id(), actor),
                new ResourceRef("trade", trade.id()));
    }

    private ObjectNode confirmationEnvelope(TradeModels.Confirmation confirmation, long tradeId, long viewer) {
        var node = json.createObjectNode();
        node.set("confirmation", views.confirmationRecord(confirmation));
        node.set("trade", queries.view(tradeId, viewer, null));
        return node;
    }

    private static TradeModels.Confirmation withId(TradeModels.Confirmation confirmation, long id) {
        return new TradeModels.Confirmation(id, confirmation.tradeId(), confirmation.agreementId(),
                confirmation.confirmerId(), confirmation.note(), confirmation.submittedAt(),
                confirmation.invalidatedAt(), confirmation.invalidationReason(), confirmation.businessEventId());
    }
}
