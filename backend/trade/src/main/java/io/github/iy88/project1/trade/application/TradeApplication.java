package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradePhase;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.AgreementStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.CancellationMode;
import io.github.iy88.project1.trade.domain.TradeVocabulary.CancellationStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.CloseReason;
import io.github.iy88.project1.trade.domain.TradeVocabulary.Decision;
import io.github.iy88.project1.trade.domain.TradeVocabulary.DisputeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.FreezeSource;
import io.github.iy88.project1.trade.domain.TradeVocabulary.InvalidationReason;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ResolutionMode;
import io.github.iy88.project1.trade.domain.TradeVocabulary.TerminalReason;
import io.github.iy88.project1.trade.domain.TradeVocabulary.WaitEndReason;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.UUID;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Trade use cases. Each write owns one WriteTransaction, lock plan and idempotency key; cross-module
 * dependencies are narrow ports invoked inside that transaction.
 */
public class TradeApplication implements TradePorts.Governance, TradePorts.GovernanceTransaction,
        TradePorts.CaseEnforcement, TradePorts.Participation, TradePorts.ReviewEligibility, TradePorts.Closure {
    private final TradeRepository repository;
    private final TradeViews views;
    private final WriteExecutor writes;
    private final TaskSchedules schedules;
    private final Clock clock;
    private final TradeSettings settings;
    private final TradePorts.Product product;
    private final TradePorts.Accounts accounts;
    private final TradePorts.Conversation conversations;
    private final TradePorts.Cases cases;
    private final TradePorts.Notifications notifications;
    private final JsonMapper json;

    public TradeApplication(TradeRepository repository, WriteExecutor writes, TaskSchedules schedules, Clock clock,
                            TradeSettings settings, TradePorts.Product product, TradePorts.Accounts accounts,
                            TradePorts.Conversation conversations, TradePorts.Cases cases,
                            TradePorts.Notifications notifications, JsonMapper json) {
        this.repository = repository;
        this.views = new TradeViews(json);
        this.writes = writes;
        this.schedules = schedules;
        this.clock = clock;
        this.settings = settings;
        this.product = product;
        this.accounts = accounts;
        this.conversations = conversations;
        this.cases = cases;
        this.notifications = notifications;
        this.json = json;
    }

    // ---------------------------------------------------------------- purchase requests

    public WriteResult<JsonNode> createPurchaseRequest(ExecutionContext context, String key,
                                                       TradeCommands.CreatePurchaseRequest command) {
        long buyer = actor(context);
        return run(context, "trade.request.create", key, command,
                (ctx, request) -> prepareCreate(buyer, request.productId()),
                (ctx, request) -> qualifySession(ctx),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    String note = optionalText(request.note(), 500, "请求说明");
                    var preview = product.read(request.productId()).orElseThrow(() -> productUnavailable());
                    requireWrite(buyer);
                    requireWrite(preview.sellerId());
                    var state = lockProduct(transaction, request.productId());
                    if (state.sellerId() == buyer) {
                        throw new BusinessError("ACTION_NOT_ALLOWED", 403, "不能购买自己的商品");
                    }
                    product.requireTradable(state, buyer);
                    if (state.contentVersion() != request.expectedProductVersion()) {
                        throw versionConflict();
                    }
                    if (repository.pendingDuplicate(state.productId(), buyer, 0)) {
                        throw new BusinessError("REQUEST_DUPLICATE", 409, "同商品已有待接受请求");
                    }
                    var now = now();
                    long tradeId = repository.insertTrade(state.productId(), buyer, state.sellerId(), note, now);
                    long conversationId = conversations.ensure(transaction, tradeId, state.productId(),
                            buyer, state.sellerId());
                    var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
                    UUID eventId = UUID.randomUUID();
                    history(transaction, trade, trade, "request.create", ActorKind.BUYER, buyer, note, null, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "request_created",
                            "买方提交了购买请求", null);
                    notify(transaction, trade, Set.of(trade.sellerId()), "trade.request_created", eventId);
                    audit(transaction, "trade.request.create", tradeId, null);
                    return new WriteResult.Response<>(201, view(tradeId, buyer, conversationId),
                            new ResourceRef("trade", tradeId));
                });
    }

    public WriteResult<JsonNode> accept(ExecutionContext context, String key, TradeCommands.Versioned command) {
        long seller = actor(context);
        return run(context, "trade.request.accept", key, command,
                (ctx, request) -> prepareAccept(seller, request.tradeId()),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
                    pre.requireSeller(seller);
                    requireWrite(pre.buyerId());
                    requireWrite(pre.sellerId());
                    var state = lockProduct(transaction, pre.productId());
                    var ids = new TreeSet<>(repository.pendingTradeIds(pre.productId(), pre.id()));
                    ids.add(pre.id());
                    var locked = new TreeMap<Long, Trade>();
                    for (long id : ids) {
                        locked.put(id, repository.lockTrade(transaction, id));
                    }
                    var trade = locked.get(pre.id());
                    requireRequestOpen(trade);
                    product.requireNoOccupancy(state, trade.id());
                    product.requireTradable(state, trade.buyerId());
                    trade.requireVersion(request.expectedVersion());

                    var pending = locked.values().stream()
                            .filter(item -> item.status() == TradeStatus.PENDING_ACCEPTANCE).toList();
                    var branches = lockBranches(transaction, pending);
                    long conversationId = branches.get(trade.id());
                    var now = now();
                    product.acquire(transaction, state, trade.id());
                    var accepted = changed(trade, TradeStatus.IN_PROGRESS, trade.activeAgreementId(), null, null,
                            now, null, now);
                    repository.save(accepted);
                    repository.insertSnapshot(state.snapshot(trade.id(), now));
                    UUID acceptedEvent = UUID.randomUUID();
                    history(transaction, trade, accepted, "request.accept", ActorKind.SELLER, seller, null, null, null, acceptedEvent, now);
                    conversations.append(transaction, conversationId, acceptedEvent, "request_accepted",
                            "卖方已接受购买请求", null);
                    notify(transaction, trade, Set.of(trade.buyerId()), "trade.request_accepted", acceptedEvent);
                    for (var other : pending) {
                        if (other.id() != trade.id()) {
                            closeRequest(transaction, other, branches.get(other.id()), CloseReason.OTHER_USER_LOCKED,
                                    "其他买方先取得商品占用", null, Set.of(other.buyerId()), now);
                        }
                    }
                    audit(transaction, "trade.request.accept", trade.id(), null);
                    return new WriteResult.Response<>(200, view(trade.id(), seller, conversationId),
                            new ResourceRef("trade", trade.id()));
                });
    }

    public WriteResult<JsonNode> reject(ExecutionContext context, String key, TradeCommands.Reject command) {
        long seller = actor(context);
        return run(context, "trade.request.reject", key, command,
                (ctx, request) -> prepareTrade(seller, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    String reason = optionalText(request.reason(), 500, "拒绝原因");
                    requireWrite(seller);
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireSeller(seller);
                    requireRequestOpen(trade);
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var now = now();
                    var rejected = changed(trade, TradeStatus.REJECTED, trade.activeAgreementId(), null, null,
                            now, null, now);
                    repository.save(rejected);
                    UUID eventId = UUID.randomUUID();
                    history(transaction, trade, rejected, "request.reject", ActorKind.SELLER, seller, reason, null, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "request_rejected",
                            "卖方拒绝了购买请求", null);
                    notify(transaction, trade, Set.of(trade.buyerId()), "trade.request_rejected", eventId);
                    archive(transaction, conversationId, trade.id(), "request_rejected");
                    audit(transaction, "trade.request.reject", trade.id(), null);
                    return new WriteResult.Response<>(200, view(trade.id(), seller, conversationId),
                            new ResourceRef("trade", trade.id()));
                });
    }

    public WriteResult<JsonNode> withdraw(ExecutionContext context, String key, TradeCommands.Versioned command) {
        long buyer = actor(context);
        return run(context, "trade.request.withdraw", key, command,
                (ctx, request) -> prepareTrade(buyer, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    requireWrite(buyer);
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireBuyer(buyer);
                    requireRequestOpen(trade);
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var now = now();
                    var withdrawn = changed(trade, TradeStatus.WITHDRAWN, trade.activeAgreementId(), null, null,
                            now, null, now);
                    repository.save(withdrawn);
                    UUID eventId = UUID.randomUUID();
                    history(transaction, trade, withdrawn, "request.withdraw", ActorKind.BUYER, buyer, null, null, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "request_withdrawn",
                            "买方撤回了购买请求", null);
                    notify(transaction, trade, Set.of(trade.sellerId()), "trade.request_withdrawn", eventId);
                    archive(transaction, conversationId, trade.id(), "request_withdrawn");
                    audit(transaction, "trade.request.withdraw", trade.id(), null);
                    return new WriteResult.Response<>(200, view(trade.id(), buyer, conversationId),
                            new ResourceRef("trade", trade.id()));
                });
    }

    // ---------------------------------------------------------------- agreements

    public WriteResult<JsonNode> proposeAgreement(ExecutionContext context, String key,
                                                  TradeCommands.ProposeAgreement command) {
        long actor = actor(context);
        return run(context, "trade.agreement.propose", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    String place = requiredText(request.deliveryPlaceText(), 200, "交付地点");
                    String method = requiredText(request.deliveryMethod(), 100, "交付方式");
                    String payment = requiredText(request.paymentMethod(), 100, "支付方式");
                    String timing = requiredText(request.paymentTiming(), 100, "支付时点");
                    if (request.deliveryAt() == null) {
                        throw inputInvalid("交付时间不能为空");
                    }
                    if (request.amountCents() < 0) {
                        throw inputInvalid("约定金额不能为负");
                    }
                    requireWrite(actor);
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    trade.requireInProgress();
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    if (repository.pendingAgreement(trade.id()).isPresent()) {
                        throw new BusinessError("AGREEMENT_ALREADY_PENDING", 409, "已有待决约定提案");
                    }
                    Long active = trade.activeAgreementId();
                    if (active == null && request.baseAgreementId() != null
                            || active != null && !active.equals(request.baseAgreementId())) {
                        throw Trade.stateConflict();
                    }
                    var now = now();
                    UUID eventId = UUID.randomUUID();
                    var agreement = new TradeModels.Agreement(0, trade.id(), request.baseAgreementId(),
                            (int) repository.nextAgreementVersion(trade.id()), AgreementStatus.PROPOSED, actor,
                            request.deliveryAt(), place, method, request.amountCents(), payment, timing, now, eventId);
                    long agreementId = repository.insertAgreement(agreement);
                    agreement = withId(agreement, agreementId);
                    var updated = changed(trade, trade.status(), trade.activeAgreementId(), trade.closeReason(),
                            trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
                    repository.save(updated);
                    historyAgreement(transaction, trade, updated,
                        active == null ? "agreement.propose" : "agreement.change.propose", trade.actorKind(actor), actor,
                        null, null, null, agreementId, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId,
                            active == null ? "agreement_proposed" : "agreement_change_proposed",
                            active == null ? "交易约定已提出" : "交易约定变更已提出",
                            new ResourceRef("agreement_proposal", agreementId));
                    notify(transaction, trade, Set.of(other(trade, actor)),
                            active == null ? "trade.agreement_proposed" : "trade.agreement_change_proposed", eventId);
                    audit(transaction, "trade.agreement.propose", trade.id(), null);
                    return new WriteResult.Response<>(201, agreementEnvelope(agreement, trade.id(), actor),
                            new ResourceRef("trade", trade.id()));
                });
    }

    public WriteResult<JsonNode> decideAgreement(ExecutionContext context, String key,
                                                 TradeCommands.DecideAgreement command) {
        long actor = actor(context);
        return run(context, "trade.agreement.decide", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    Decision decision = decision(request.decision());
                    requireWrite(actor);
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    trade.requireInProgress();
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var agreement = repository.agreement(request.agreementId())
                            .orElseThrow(() -> new BusinessError("AGREEMENT_NOT_PENDING", 409, "约定提案不存在"));
                    if (agreement.tradeId() != trade.id()
                            || agreement.status() != AgreementStatus.PROPOSED) {
                        throw new BusinessError("AGREEMENT_NOT_PENDING", 409, "约定提案已决或不属于本交易");
                    }
                    if (decision == Decision.WITHDRAW) {
                        if (agreement.proposedBy() != actor) {
                            throw Trade.actionNotAllowed();
                        }
                    } else if (agreement.proposedBy() == actor) {
                        throw Trade.actionNotAllowed();
                    }
                    var now = now();
                    UUID eventId = UUID.randomUUID();
                    var storedDecision = new TradeModels.Decision(0, agreement.id(), decision, actor, now, eventId);
                    long decisionId = repository.insertAgreementDecision(storedDecision);
                    AgreementStatus target = switch (decision) {
                        case ACCEPT -> AgreementStatus.EFFECTIVE;
                        case REJECT -> AgreementStatus.REJECTED;
                        case WITHDRAW -> AgreementStatus.WITHDRAWN;
                    };
                    Long active = trade.activeAgreementId();
                    if (decision == Decision.ACCEPT && agreement.baseAgreementId() != null) {
                        // Supersede the old effective row before the partial unique index accepts the new one.
                        repository.supersedeEffective(trade.id(), agreement.id());
                        repository.invalidateConfirmations(trade.id(), InvalidationReason.AGREEMENT_CHANGED, now);
                        endWait(transaction, trade.id(), WaitEndReason.AGREEMENT_CHANGED, now);
                    }
                    repository.setAgreementStatus(agreement.id(), target);
                    if (decision == Decision.ACCEPT) {
                        active = agreement.id();
                    }
                    var updated = changed(trade, trade.status(), active, trade.closeReason(), trade.terminalReason(),
                            trade.respondedAt(), trade.endedAt(), now);
                    repository.save(updated);
                    historyAgreement(transaction, trade, updated, "agreement." + decision.value(),
                        trade.actorKind(actor), actor, null, null, null, agreement.id(), decisionId, eventId, now);
                    String type = switch (decision) {
                        case ACCEPT -> "agreement_confirmed";
                        case REJECT -> "agreement_rejected";
                        case WITHDRAW -> "agreement_withdrawn";
                    };
                    conversations.append(transaction, conversationId, eventId, type,
                            switch (decision) {
                                case ACCEPT -> "交易约定已生效";
                                case REJECT -> "交易约定被拒绝";
                                case WITHDRAW -> "交易约定已撤回";
                            }, new ResourceRef("agreement_decision", decisionId));
                    notify(transaction, trade, Set.of(other(trade, actor)),
                            "trade." + type, eventId);
                    audit(transaction, "trade.agreement." + decision.value(), trade.id(), null);
                    return new WriteResult.Response<>(200,
                            agreementEnvelope(repository.agreement(agreement.id()).orElseThrow(), trade.id(), actor),
                            new ResourceRef("trade", trade.id()));
                });
    }

    // ---------------------------------------------------------------- completion

    public WriteResult<JsonNode> submitConfirmation(ExecutionContext context, String key,
                                                    TradeCommands.ConfirmCompletion command) {
        long actor = actor(context);
        return run(context, "trade.confirmation.submit", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), true, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    String note = optionalText(request.note(), 1000, "确认说明");
                    var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
                    requireWrite(actor);
                    var state = lockProduct(transaction, pre.productId());
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    trade.requireInProgress();
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var effective = repository.currentAgreement(trade.id())
                            .orElseThrow(() -> new BusinessError("AGREEMENT_REQUIRED", 409, "尚无生效约定"));
                    if (trade.activeAgreementId() == null || effective.id() != trade.activeAgreementId()) {
                        throw Trade.stateConflict();
                    }
                    var current = repository.currentConfirmations(trade.id());
                    if (current.stream().anyMatch(item -> item.confirmerId() == actor)) {
                        throw new BusinessError("CONFIRMATION_ALREADY_SUBMITTED", 409, "本人已提交确认");
                    }
                    var now = now();
                    var confirmation = new TradeModels.Confirmation(0, trade.id(), effective.id(),
                            actor, note, now, null, null, UUID.randomUUID());
                    long confirmationId = repository.insertConfirmation(confirmation);
                    confirmation = withId(confirmation, confirmationId);
                    var counterpart = current.stream()
                            .filter(item -> item.confirmerId() == other(trade, actor))
                            .filter(item -> item.agreementId() == effective.id())
                            .findFirst();
                    if (counterpart.isPresent()) {
                        var completed = changed(trade, TradeStatus.COMPLETED, trade.activeAgreementId(), null,
                                TerminalReason.COMPLETED.value(), trade.respondedAt(), now, now);
                        repository.save(completed);
                        endWait(transaction, trade.id(), WaitEndReason.COMPLETED, now);
                        endFreezes(transaction, trade.id(), now);
                        repository.terminateOpenDisputes(trade.id(), now);
                        product.release(transaction, state, trade.id(), "completed");
                        UUID confirmationEvent = confirmation.businessEventId();
                        historyConfirmation(transaction, trade, completed, "completion.confirm",
                                trade.actorKind(actor), actor, note, null, null, effective.id(), confirmationId,
                                confirmationEvent, now);
                        conversations.append(transaction, conversationId, confirmationEvent, "completion_confirmed",
                                "完成确认已提交", new ResourceRef("completion_confirmation", confirmationId));
                        UUID completedEvent = UUID.randomUUID();
                        long completedHistory = historyConfirmation(transaction, trade, completed,
                                "trade.completed", ActorKind.SYSTEM, null, null, null, null, effective.id(),
                                confirmationId, completedEvent, now);
                        conversations.append(transaction, conversationId, completedEvent, "trade_completed",
                                "交易已完成，商品已下架。如需继续出售，可前往商品详情重新上架。",
                                new ResourceRef("trade_transition", completedHistory));
                        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()),
                                "trade.completed", completedEvent);
                        archive(transaction, conversationId, trade.id(), "completed");
                    } else {
                        var updated = changed(trade, trade.status(), trade.activeAgreementId(), trade.closeReason(),
                                trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
                        repository.save(updated);
                        var wait = TradeModels.Wait.start(now, settings.confirmationWaitSeconds(),
                                settings.policyVersion());
                        repository.saveWait(trade.id(), wait);
                        scheduleTimeout(trade.id(), wait, now);
                        UUID eventId = confirmation.businessEventId();
                        historyConfirmation(transaction, trade, updated, "completion.confirm",
                                trade.actorKind(actor), actor, note, null, null, effective.id(), confirmationId,
                                eventId, now);
                        conversations.append(transaction, conversationId, eventId, "completion_confirmed",
                                "完成确认已提交，等待对方确认", new ResourceRef("completion_confirmation",
                                        confirmationId));
                        notify(transaction, trade, Set.of(other(trade, actor)), "trade.completion_confirmed", eventId);
                    }
                    audit(transaction, "trade.confirmation.submit", trade.id(), null);
                    return new WriteResult.Response<>(201, confirmationEnvelope(confirmation, trade.id(), actor),
                            new ResourceRef("trade", trade.id()));
                });
    }

    // ---------------------------------------------------------------- cancellation

    public WriteResult<JsonNode> proposeCancellation(ExecutionContext context, String key,
                                                     TradeCommands.ProposeCancellation command) {
        long actor = actor(context);
        return run(context, "trade.cancellation.propose", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), true, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    String reason = optionalText(request.reason(), 500, "取消原因");
                    var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
                    requireWrite(actor);
                    var state = lockProduct(transaction, pre.productId());
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    requireCancellable(trade);
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    if (repository.pendingCancellation(trade.id()).isPresent()) {
                        throw new BusinessError("CANCELLATION_ALREADY_PENDING", 409, "已有待决取消申请");
                    }
                    var now = now();
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
                        var terminated = changed(trade, TradeStatus.TERMINATED, trade.activeAgreementId(), null,
                                TerminalReason.CANCELLED.value(), trade.respondedAt(), now, now);
                        repository.save(terminated);
                        endWait(transaction, trade.id(), WaitEndReason.TERMINATED, now);
                        endFreezes(transaction, trade.id(), now);
                        repository.terminateOpenDisputes(trade.id(), now);
                        product.release(transaction, state, trade.id(), "cancelled");
                    historyCancellation(transaction, trade, terminated, "cancellation.request", trade.actorKind(actor),
                        actor, reason, null, null, proposalId, null, requestEvent, now);
                        conversations.append(transaction, conversationId, requestEvent, "cancellation_requested",
                                "买方直接取消了交易", new ResourceRef("cancellation_request", proposalId));
                    historyCancellation(transaction, trade, terminated, "cancellation.accept", ActorKind.BUYER, actor,
                        reason, null, null, proposalId, decisionId, decisionEvent, now);
                        conversations.append(transaction, conversationId, decisionEvent, "cancellation_accepted",
                                "交易已终止", new ResourceRef("cancellation_decision", decisionId));
                        UUID terminatedEvent = UUID.randomUUID();
                        long terminatedHistory = historyCancellation(transaction, trade, terminated, "trade.terminated",
                            ActorKind.SYSTEM, null, reason, null, null, proposalId, decisionId, terminatedEvent, now);
                        conversations.append(transaction, conversationId, terminatedEvent, "trade_terminated",
                                "交易已终止，商品已下架。如需继续出售，可前往商品详情重新上架。", new ResourceRef("trade_transition", terminatedHistory));
                        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()),
                                "trade.terminated", terminatedEvent);
                        archive(transaction, conversationId, trade.id(), "cancelled");
                    } else {
                        var updated = changed(trade, trade.status(), trade.activeAgreementId(), trade.closeReason(),
                                trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
                        repository.save(updated);
                    historyCancellation(transaction, trade, updated, "cancellation.request", trade.actorKind(actor),
                        actor, reason, null, null, proposalId, null, requestEvent, now);
                        conversations.append(transaction, conversationId, requestEvent, "cancellation_requested",
                                "取消申请已提交", new ResourceRef("cancellation_request", proposalId));
                        notify(transaction, trade, Set.of(other(trade, actor)),
                                "trade.cancellation_requested", requestEvent);
                    }
                    audit(transaction, "trade.cancellation.propose", trade.id(), null);
                    var body = json.createObjectNode();
                    body.put("mode", proposal.mode().value());
                    body.set("proposal", views.cancellationRecord(proposal));
                    body.set("trade", view(trade.id(), actor, conversationId));
                    return new WriteResult.Response<>(201, body, new ResourceRef("trade", trade.id()));
                });
    }

    public WriteResult<JsonNode> decideCancellation(ExecutionContext context, String key,
                                                    TradeCommands.DecideCancellation command) {
        long actor = actor(context);
        return run(context, "trade.cancellation.decide", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), true, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    Decision decision = decision(request.decision());
                    var pre = repository.find(request.tradeId()).orElseThrow(Trade::notVisible);
                    requireWrite(actor);
                    var state = lockProduct(transaction, pre.productId());
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    requireCancellable(trade);
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var proposal = repository.cancellation(request.cancellationId())
                            .orElseThrow(() -> new BusinessError("CANCELLATION_NOT_PENDING", 409,
                                    "取消申请不存在"));
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
                    var now = now();
                    UUID decisionEvent = UUID.randomUUID();
                    var stored = new TradeModels.CancellationDecision(0, proposal.id(), decision, actor, now,
                            decisionEvent);
                    long decisionId = repository.insertCancellationDecision(stored);
                    if (decision == Decision.ACCEPT) {
                        repository.setCancellationStatus(proposal.id(), CancellationStatus.ACCEPTED);
                        var terminated = changed(trade, TradeStatus.TERMINATED, trade.activeAgreementId(), null,
                                TerminalReason.CANCELLED.value(), trade.respondedAt(), now, now);
                        repository.save(terminated);
                        endWait(transaction, trade.id(), WaitEndReason.TERMINATED, now);
                        endFreezes(transaction, trade.id(), now);
                        repository.terminateOpenDisputes(trade.id(), now);
                        product.release(transaction, state, trade.id(), "cancelled");
                    historyCancellation(transaction, trade, terminated, "cancellation.accept", trade.actorKind(actor),
                        actor, null, null, null, proposal.id(), decisionId, decisionEvent, now);
                        conversations.append(transaction, conversationId, decisionEvent, "cancellation_accepted",
                                "取消申请已同意，交易终止", new ResourceRef("cancellation_decision", decisionId));
                        UUID terminatedEvent = UUID.randomUUID();
                        long terminatedHistory = historyCancellation(transaction, trade, terminated, "trade.terminated",
                            ActorKind.SYSTEM, null, null, null, null, proposal.id(), decisionId, terminatedEvent, now);
                        conversations.append(transaction, conversationId, terminatedEvent, "trade_terminated",
                                "交易已终止，商品已下架。如需继续出售，可前往商品详情重新上架。", new ResourceRef("trade_transition", terminatedHistory));
                        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.terminated",
                                terminatedEvent);
                        archive(transaction, conversationId, trade.id(), "cancelled");
                    } else {
                        repository.setCancellationStatus(proposal.id(),
                                decision == Decision.REJECT ? CancellationStatus.REJECTED
                                        : CancellationStatus.WITHDRAWN);
                        var updated = changed(trade, trade.status(), trade.activeAgreementId(), trade.closeReason(),
                                trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
                        repository.save(updated);
                        String action = decision == Decision.REJECT ? "cancellation.reject" : "cancellation.withdraw";
                        historyCancellation(transaction, trade, updated, action, trade.actorKind(actor), actor, null, null,
                            null, proposal.id(), decisionId, decisionEvent, now);
                        String type = decision == Decision.REJECT ? "cancellation_rejected" : "cancellation_withdrawn";
                        conversations.append(transaction, conversationId, decisionEvent, type,
                                decision == Decision.REJECT ? "取消申请被拒绝" : "取消申请已撤回",
                                new ResourceRef("cancellation_decision", decisionId));
                        notify(transaction, trade, Set.of(other(trade, actor)), "trade." + type, decisionEvent);
                    }
                    audit(transaction, "trade.cancellation." + decision.value(), trade.id(), null);
                    var updatedProposal = repository.cancellation(proposal.id()).orElseThrow();
                    var body = json.createObjectNode();
                    body.set("proposal", views.cancellationRecord(updatedProposal));
                    body.set("trade", view(trade.id(), actor, conversationId));
                    return new WriteResult.Response<>(200, body,
                            new ResourceRef("trade", trade.id()));
                });
    }

    // ---------------------------------------------------------------- disputes

    public WriteResult<JsonNode> openDispute(ExecutionContext context, String key,
                                             TradeCommands.OpenDispute command) {
        long actor = actor(context);
        return run(context, "trade.dispute.open", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    String statement = requiredText(request.statement(), 2000, "争议说明");
                    requireWrite(actor);
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    if (trade.status() == TradeStatus.DISPUTED) {
                        throw new BusinessError("DISPUTE_ALREADY_OPEN", 409, "已有未解决争议");
                    }
                    trade.requireInProgress();
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var now = now();
                    endWait(transaction, trade.id(), WaitEndReason.DISPUTED, now);
                    long disputeId = repository.insertDispute(trade.id(), actor, statement, now);
                    var dispute = repository.dispute(disputeId).orElseThrow();
                    var disputed = changed(trade, TradeStatus.DISPUTED, trade.activeAgreementId(), trade.closeReason(),
                            trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
                    repository.save(disputed);
                    UUID eventId = UUID.randomUUID();
                    long disputeHistory = historyDispute(transaction, trade, disputed, "dispute.open",
                        trade.actorKind(actor), actor, statement, null, null, disputeId, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "dispute_opened", "交易争议已发起",
                            new ResourceRef("trade_transition", disputeHistory));
                    audit(transaction, "trade.dispute.open", trade.id(), null);
                    var body = json.createObjectNode();
                    body.set("dispute", views.disputeRecord(dispute));
                    body.set("trade", view(trade.id(), actor, conversationId));
                    return new WriteResult.Response<>(201, body, new ResourceRef("trade", trade.id()));
                });
    }

    public WriteResult<JsonNode> confirmResolution(ExecutionContext context, String key,
                                                   TradeCommands.ConfirmResolution command) {
        long actor = actor(context);
        return run(context, "trade.dispute.resolve", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> {
                    requireWrite(actor);
                    var trade = repository.lockTrade(transaction, request.tradeId());
                    trade.requireNotTerminal();
                    if (trade.status() != TradeStatus.DISPUTED) {
                        throw new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在");
                    }
                    requireNotFrozen(transaction, trade.id());
                    trade.requireVersion(request.expectedVersion());
                    long conversationId = requireConversation(transaction, trade.id());
                    var dispute = repository.dispute(request.disputeId())
                            .orElseThrow(() -> new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在"));
                    if (dispute.tradeId() != trade.id() || dispute.status() != DisputeStatus.OPEN) {
                        throw new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在");
                    }
                    var now = now();
                    var existing = repository.resolutionConfirmations(dispute.id()).stream()
                            .filter(item -> item.confirmerId() == actor).findFirst();
                    if (existing.isPresent()) {
                        var body = json.createObjectNode();
                        body.set("dispute", views.disputeRecord(dispute));
                        body.set("trade", view(trade.id(), actor, conversationId));
                        return new WriteResult.Response<>(200, body, new ResourceRef("trade", trade.id()));
                    }
                    UUID eventId = UUID.randomUUID();
                    var confirmation = new TradeModels.ResolutionConfirmation(0, dispute.id(), actor, now, eventId);
                    long confirmationId = repository.insertResolutionConfirmation(confirmation);
                    var confirmations = repository.resolutionConfirmations(dispute.id());
                    if (confirmations.size() >= 2) {
                        repository.resolveDispute(dispute.id(), ResolutionMode.SELF, actor, null, now);
                        repository.invalidateConfirmations(trade.id(), InvalidationReason.DISPUTE_RESOLVED, now);
                        var resolved = changed(trade, TradeStatus.IN_PROGRESS, trade.activeAgreementId(),
                                trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(),
                                now);
                        repository.save(resolved);
                    historyDispute(transaction, trade, resolved, "dispute.resolution_confirm", trade.actorKind(actor),
                        actor, null, null, null, dispute.id(), confirmationId, eventId, now);
                        UUID resolvedEvent = UUID.randomUUID();
                    long resolvedHistory = historyDispute(transaction, trade, resolved, "dispute.resolve",
                        ActorKind.SYSTEM, null, null, null, null, dispute.id(), confirmationId, resolvedEvent, now);
                        conversations.append(transaction, conversationId, resolvedEvent, "dispute_resolved",
                                "双方确认争议已解决，交易恢复进行", new ResourceRef("trade_transition", resolvedHistory));
                    } else {
                        var updated = changed(trade, trade.status(), trade.activeAgreementId(), trade.closeReason(),
                                trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
                        repository.save(updated);
                    historyDispute(transaction, trade, updated, "dispute.resolution_confirm", trade.actorKind(actor),
                        actor, null, null, null, dispute.id(), confirmationId, eventId, now);
                        conversations.append(transaction, conversationId, eventId, "dispute_resolution_confirmed",
                                "一方已确认争议解决", new ResourceRef("dispute_resolution_confirmation",
                                        confirmationId));
                    }
                    audit(transaction, "trade.dispute.resolve", trade.id(), null);
                    var body = json.createObjectNode();
                    body.set("dispute", views.disputeRecord(repository.dispute(dispute.id()).orElseThrow()));
                    body.set("trade", view(trade.id(), actor, conversationId));
                    return new WriteResult.Response<>(200, body, new ResourceRef("trade", trade.id()));
                });
    }

    // ---------------------------------------------------------------- governance commands

    public WriteResult<JsonNode> freeze(ExecutionContext context, String key, TradeCommands.Freeze command) {
        long manager = actor(context);
        return run(context, "trade.freeze", key, command,
                (ctx, request) -> prepareGovernance(manager, request.tradeId(), request.caseId(), false),
                (ctx, request) -> qualifyGovernance(ctx, request.tradeId()),
                this::replayGovernance,
                (transaction, request, qualification) -> {
                    var outcome = freezeInTransaction(transaction, context, request.caseId(), request.tradeId(),
                            request.basisRef(), request.reason());
                    return new WriteResult.Response<>(200, governanceView(outcome),
                            new ResourceRef("trade", outcome.tradeId()));
                });
    }

    @Override
    public LockPlan governancePlan(long managerId, long tradeId, long caseId, boolean product) {
        return prepareGovernance(managerId, tradeId, caseId, product);
    }

    @Override
    public TradePorts.CaseEnforcementPlan prepare(long managerId, long tradeId, long caseId, boolean product) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        long conversationId = requireConversationId(tradeId);
        var accountsSet = new TreeSet<Long>(List.of(managerId, trade.buyerId(), trade.sellerId()));
        var resources = new TreeSet<LockPlan.Key>();
        if (product) {
            resources.add(productKey(trade.productId()));
        }
        resources.add(tradeKey(tradeId));
        resources.add(caseKey(caseId));
        resources.add(conversationKey(conversationId));
        return new TradePorts.CaseEnforcementPlan(new LockPlan(sharedAccounts(accountsSet), resources),
                conversationId, product ? trade.productId() : null);
    }

    @Override
    public void lockTrade(WriteTransaction transaction, long tradeId) {
        repository.lockTrade(transaction, tradeId);
    }

    @Override
    public void lockConversation(WriteTransaction transaction, long conversationId) {
        conversations.lockConversation(transaction, conversationId);
    }

    @Override
    public void lockCaseProduct(WriteTransaction transaction, long productId) {
        lockProduct(transaction, productId);
    }

    @Override
    public TradePorts.CaseEnforcementOutcome freezeLocked(WriteTransaction transaction, long caseId, long tradeId,
                                                          String basisRef, String reason) {
        var trade = requireLockedTrade(transaction, caseId, tradeId);
        long manager = actor(transaction.context());
        String validatedReason = requiredText(reason, 500, "冻结原因");
        requireWrite(manager);
        requireFreezable(trade);
        return freezeFacts(transaction, trade, caseId, manager, basisRef, validatedReason, now(),
                UUID.randomUUID()).orElseThrow(() -> new BusinessError(
                        "TARGET_STATE_CONFLICT", 409, "已有事项冻结缺少原始执行记录"));
    }

    @Override
    public TradePorts.GovernanceOutcome freezeInTransaction(WriteTransaction transaction, ExecutionContext context,
                                                            long caseId, long tradeId, String basisRef,
                                                            String reason) {
        long manager = actor(context);
        String validatedReason = requiredText(reason, 500, "冻结原因");
        requireWrite(manager);
        var trade = repository.lockTrade(transaction, tradeId);
        requireFreezable(trade);
        lockCase(transaction, caseId, manager, trade.id(), basisRef);
        long conversationId = requireConversation(transaction, trade.id());
        UUID eventId = UUID.randomUUID();
        var outcome = freezeFacts(transaction, trade, caseId, manager, basisRef, validatedReason, now(), eventId);
        outcome.filter(frozen -> !frozen.alreadyEffective()).ifPresent(frozen -> {
            conversations.append(transaction, conversationId, eventId, "trade_frozen",
                    "交易已被冻结", frozen.transitionRef());
            notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.frozen", eventId);
            audit(transaction, "trade.freeze", trade.id(), new ResourceRef("case", caseId));
        });
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> liftFreeze(ExecutionContext context, String key,
                                            TradeCommands.LiftFreeze command) {
        long manager = actor(context);
        return run(context, "trade.freeze.lift", key, command,
                (ctx, request) -> prepareGovernance(manager, request.tradeId(), request.caseId(), false),
                (ctx, request) -> qualifyGovernance(ctx, request.tradeId()),
                this::replayGovernance,
                (transaction, request, qualification) -> {
                    var outcome = liftFreezeInTransaction(transaction, context, request.caseId(),
                            request.tradeId(), request.freezeId(), request.basisRef(), request.reason());
                    return new WriteResult.Response<>(200, governanceView(outcome),
                            new ResourceRef("trade", outcome.tradeId()));
                });
    }

    @Override
    public TradePorts.CaseEnforcementOutcome liftFreezeLocked(WriteTransaction transaction, long caseId,
                                                              long tradeId, long freezeTransitionId,
                                                              String basisRef, String reason) {
        var trade = requireLockedTrade(transaction, caseId, tradeId);
        long manager = actor(transaction.context());
        String validatedReason = requiredText(reason, 500, "解除原因");
        requireWrite(manager);
        if (trade.status().isTerminal()) {
            throw freezeNotActive();
        }
        var history = repository.history(freezeTransitionId).orElseThrow(TradeApplication::freezeNotActive);
        if (history.freezeId() == null) {
            throw freezeNotActive();
        }
        var freeze = repository.freeze(history.freezeId()).orElseThrow(TradeApplication::freezeNotActive);
        if (!exactAdminCaseFreeze(history, freeze, trade, caseId)) {
            throw freezeNotActive();
        }
        return liftFreezeFacts(transaction, trade, freeze, caseId, manager, basisRef, validatedReason, now(),
                UUID.randomUUID());
    }

    @Override
    public TradePorts.GovernanceOutcome liftFreezeInTransaction(WriteTransaction transaction,
                                                                ExecutionContext context, long caseId, long tradeId,
                                                                long freezeId, String basisRef, String reason) {
        long manager = actor(context);
        String validatedReason = requiredText(reason, 500, "解除原因");
        requireWrite(manager);
        var trade = repository.lockTrade(transaction, tradeId);
        trade.requireNotTerminal();
        lockCase(transaction, caseId, manager, trade.id(), basisRef);
        long conversationId = requireConversation(transaction, trade.id());
        var freeze = repository.freeze(freezeId).orElseThrow(TradeApplication::freezeNotActive);
        if (freeze.tradeId() != trade.id() || !freeze.active()) {
            throw freezeNotActive();
        }
        UUID eventId = UUID.randomUUID();
        var outcome = liftFreezeFacts(transaction, trade, freeze, caseId, manager, basisRef, validatedReason,
                now(), eventId);
        conversations.append(transaction, conversationId, eventId, "trade_unfrozen", "交易冻结已解除",
                outcome.transitionRef());
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.unfrozen", eventId);
        audit(transaction, "trade.freeze.lift", trade.id(), new ResourceRef("case", caseId));
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> adjustStatus(ExecutionContext context, String key,
                                              TradeCommands.AdjustStatus command) {
        long manager = actor(context);
        return run(context, "trade.adjust", key, command,
                (ctx, request) -> prepareGovernance(manager, request.tradeId(), request.caseId(), true),
                (ctx, request) -> qualifyGovernance(ctx, request.tradeId()),
                this::replayGovernance,
                (transaction, request, qualification) -> {
                    var outcome = adjustStatusInTransaction(transaction, context, request.caseId(),
                            request.tradeId(), request.targetStatus(), request.basisRef(), request.reason());
                    return new WriteResult.Response<>(200, governanceView(outcome),
                            new ResourceRef("trade", outcome.tradeId()));
                });
    }

    @Override
    public TradePorts.CaseEnforcementOutcome adjustStatusLocked(WriteTransaction transaction, long caseId,
                                                                long tradeId, String targetStatus, String basisRef,
                                                                String reason) {
        var trade = requireLockedTrade(transaction, caseId, tradeId);
        long manager = actor(transaction.context());
        TradeStatus target = terminalTarget(targetStatus);
        String validatedReason = requiredText(reason, 500, "调整原因");
        requireWrite(manager);
        trade.requireNotTerminal();
        transaction.requireLocked(productKey(trade.productId()));
        var state = product.read(trade.productId()).orElseThrow(TradeApplication::productUnavailable);
        return adjustStatusFacts(transaction, trade, state, target, caseId, manager, basisRef,
                validatedReason, now(), UUID.randomUUID());
    }

    @Override
    public TradePorts.GovernanceOutcome adjustStatusInTransaction(WriteTransaction transaction,
                                                                  ExecutionContext context, long caseId,
                                                                  long tradeId, String targetStatus,
                                                                  String basisRef, String reason) {
        long manager = actor(context);
        TradeStatus target = terminalTarget(targetStatus);
        String validatedReason = requiredText(reason, 500, "调整原因");
        var pre = repository.find(tradeId).orElseThrow(Trade::notVisible);
        requireWrite(manager);
        var state = lockProduct(transaction, pre.productId());
        var trade = repository.lockTrade(transaction, tradeId);
        trade.requireNotTerminal();
        lockCase(transaction, caseId, manager, trade.id(), basisRef);
        long conversationId = requireConversation(transaction, trade.id());
        UUID eventId = UUID.randomUUID();
        var outcome = adjustStatusFacts(transaction, trade, state, target, caseId, manager, basisRef,
                validatedReason, now(), eventId);
        conversations.append(transaction, conversationId, eventId,
                target == TradeStatus.COMPLETED ? "trade_completed" : "trade_terminated",
                "管理员调整交易状态，如需继续出售，可前往商品详情重新上架。", outcome.transitionRef());
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.adjusted", eventId);
        archive(transaction, conversationId, trade.id(), "admin_" + target.value());
        audit(transaction, "trade.adjust", trade.id(), new ResourceRef("case", caseId));
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> restore(ExecutionContext context, String key, TradeCommands.Restore command) {
        long manager = actor(context);
        return run(context, "trade.restore", key, command,
                (ctx, request) -> prepareGovernance(manager, request.tradeId(), request.caseId(), false),
                (ctx, request) -> qualifyGovernance(ctx, request.tradeId()),
                this::replayGovernance,
                (transaction, request, qualification) -> {
                    var outcome = restoreInTransaction(transaction, context, request.caseId(), request.tradeId(),
                            request.basisRef(), request.reason());
                    return new WriteResult.Response<>(200, governanceView(outcome),
                            new ResourceRef("trade", outcome.tradeId()));
                });
    }

    @Override
    public TradePorts.CaseEnforcementOutcome restoreLocked(WriteTransaction transaction, long caseId, long tradeId,
                                                           String basisRef, String reason) {
        var trade = requireLockedTrade(transaction, caseId, tradeId);
        long manager = actor(transaction.context());
        String validatedReason = requiredText(reason, 500, "恢复原因");
        requireWrite(manager);
        trade.requireNotTerminal();
        if (trade.status() != TradeStatus.ABNORMAL) {
            throw restoreNotAllowed();
        }
        return restoreFacts(transaction, trade, caseId, manager, basisRef, validatedReason, now(),
                UUID.randomUUID());
    }

    @Override
    public TradePorts.GovernanceOutcome restoreInTransaction(WriteTransaction transaction,
                                                             ExecutionContext context, long caseId, long tradeId,
                                                             String basisRef, String reason) {
        long manager = actor(context);
        String validatedReason = requiredText(reason, 500, "恢复原因");
        requireWrite(manager);
        var trade = repository.lockTrade(transaction, tradeId);
        trade.requireNotTerminal();
        if (trade.status() != TradeStatus.ABNORMAL) {
            throw restoreNotAllowed();
        }
        lockCase(transaction, caseId, manager, trade.id(), basisRef);
        long conversationId = requireConversation(transaction, trade.id());
        UUID eventId = UUID.randomUUID();
        var outcome = restoreFacts(transaction, trade, caseId, manager, basisRef, validatedReason, now(), eventId);
        conversations.append(transaction, conversationId, eventId, "trade_restored",
                "异常交易已恢复进行", outcome.transitionRef());
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.restored", eventId);
        audit(transaction, "trade.restore", trade.id(), new ResourceRef("case", caseId));
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> resolveDisputeAsAdmin(ExecutionContext context, String key,
                                                       TradeCommands.ResolveDispute command) {
        long manager = actor(context);
        return run(context, "trade.dispute.admin_resolve", key, command,
                (ctx, request) -> {
                    var dispute = repository.dispute(request.disputeId())
                            .orElseThrow(() -> new BusinessError("DISPUTE_NOT_OPEN", 409, "争议不存在"));
                    return prepareGovernance(manager, dispute.tradeId(), request.caseId(), false);
                },
                (ctx, request) -> {
                    var dispute = repository.dispute(request.disputeId())
                            .orElseThrow(() -> new BusinessError("DISPUTE_NOT_OPEN", 409, "争议不存在"));
                    return qualifyGovernance(ctx, dispute.tradeId());
                },
                this::replayGovernance,
                (transaction, request, qualification) -> {
                    var outcome = resolveDisputeInTransaction(transaction, context, request.caseId(),
                            request.disputeId(), request.basisRef(), request.reason());
                    return new WriteResult.Response<>(200, governanceView(outcome),
                            new ResourceRef("trade", outcome.tradeId()));
                });
    }

    @Override
    public TradePorts.GovernanceOutcome resolveDisputeInTransaction(WriteTransaction transaction,
                                                                    ExecutionContext context, long caseId,
                                                                    long disputeId, String basisRef, String reason) {
        long manager = actor(context);
        String validatedReason = requiredText(reason, 500, "处理原因");
        var found = repository.dispute(disputeId)
                .orElseThrow(() -> new BusinessError("DISPUTE_NOT_OPEN", 409, "争议不存在"));
        var pre = repository.find(found.tradeId()).orElseThrow(Trade::notVisible);
        requireWrite(manager);
        var trade = repository.lockTrade(transaction, found.tradeId());
        trade.requireNotTerminal();
        if (trade.status() != TradeStatus.DISPUTED) {
            throw new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在");
        }
        lockCase(transaction, caseId, manager, trade.id(), basisRef);
        long conversationId = requireConversation(transaction, trade.id());
        var dispute = repository.dispute(disputeId).orElseThrow();
        if (dispute.tradeId() != trade.id() || dispute.status() != DisputeStatus.OPEN) {
            throw new BusinessError("DISPUTE_NOT_OPEN", 409, "争议已解决或不存在");
        }
        var now = now();
        repository.resolveDispute(dispute.id(), ResolutionMode.ADMIN, manager, caseId, now);
        repository.invalidateConfirmations(trade.id(), InvalidationReason.DISPUTE_RESOLVED, now);
        endWait(transaction, trade.id(), WaitEndReason.DISPUTED, now);
        var restored = changed(trade, TradeStatus.IN_PROGRESS, trade.activeAgreementId(),
                trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
        repository.save(restored);
        UUID eventId = UUID.randomUUID();
        long historyId = historyDisputeAgreement(transaction, trade, restored, "dispute.resolve",
                ActorKind.ADMIN, manager, validatedReason, basisRef, caseId, trade.activeAgreementId(),
                dispute.id(), eventId, now);
        conversations.append(transaction, conversationId, eventId, "dispute_resolved",
                "管理员已解决交易争议", new ResourceRef("trade_transition", historyId));
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.dispute_resolved",
                eventId);
        audit(transaction, "trade.dispute.admin_resolve", trade.id(), new ResourceRef("case", caseId));
        return governanceOutcome(trade.id());
    }


    // ---------------------------------------------------------------- product/account triggered closure

    @Override
    public LockPlan productClosurePlan(long productId) {
        return closurePlan(repository.pendingTradeIdsForProduct(productId));
    }

    @Override
    public LockPlan accountBanPlan(long accountId) {
        return closurePlan(accountTradeIds(accountId));
    }

    @Override
    public void closePendingForProduct(WriteTransaction transaction, LockPlan plan, long productId,
                                       CloseReason reason, String basisRef) {
        var trades = lockAffected(transaction, plan, repository.pendingTradeIdsForProduct(productId)).stream()
                .filter(trade -> trade.status() == TradeStatus.PENDING_ACCEPTANCE).toList();
        var branches = lockBranches(transaction, trades);
        var now = now();
        for (var trade : trades) {
            closeRequest(transaction, trade, branches.get(trade.id()), reason, reason.value(), basisRef,
                    Set.of(trade.buyerId()), now);
        }
    }

    @Override
    public void applyAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                                long restrictionId, String reason, String basisRef) {
        var trades = lockAffected(transaction, plan, accountTradeIds(accountId)).stream()
                .filter(trade -> trade.status() == TradeStatus.PENDING_ACCEPTANCE || trade.status().isActive())
                .toList();
        var branches = lockBranches(transaction, trades);
        var now = now();
        for (var trade : trades) {
            long branch = branches.get(trade.id());
            var parties = Set.of(trade.buyerId(), trade.sellerId());
            if (trade.status() == TradeStatus.PENDING_ACCEPTANCE) {
                closeRequest(transaction, trade, branch, CloseReason.ACCOUNT_BANNED, reason, basisRef, parties, now);
            } else if (accountFreeze(trade.id(), restrictionId).isEmpty()) {
                repository.insertFreeze(trade.id(), FreezeSource.ACCOUNT_BAN, restrictionId, reason, now);
                pauseWait(transaction, trade.id(), now);
                repository.touch(trade.id(), now);
                UUID event = UUID.randomUUID();
                long historyId = history(transaction, trade, trade, "trade.freeze", ActorKind.SYSTEM, null,
                        reason, basisRef, null, event, now);
                conversations.append(transaction, branch, event, "trade_frozen",
                        "账户受限，交易已冻结", new ResourceRef("trade_transition", historyId));
                notify(transaction, trade, parties, "trade.frozen", event);
            }
        }
    }

    @Override
    public void removeAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                                 long restrictionId, String basisRef) {
        var trades = lockAffected(transaction, plan, repository.activeTradeIdsForAccount(accountId)).stream()
                .filter(trade -> trade.status().isActive()).toList();
        var branches = lockBranches(transaction, trades);
        var now = now();
        for (var trade : trades) {
            var freeze = accountFreeze(trade.id(), restrictionId);
            if (freeze.isEmpty()) {
                continue;
            }
            repository.endFreeze(freeze.orElseThrow().id(), null, now);
            repository.touch(trade.id(), now);
            resumeWaitIfPossible(transaction, trade, now);
            UUID event = UUID.randomUUID();
            long historyId = history(transaction, trade, trade, "trade.unfreeze", ActorKind.SYSTEM, null,
                    null, basisRef, null, event, now);
            conversations.append(transaction, branches.get(trade.id()), event, "trade_unfrozen", "交易冻结已解除",
                    new ResourceRef("trade_transition", historyId));
            notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.unfrozen", event);
        }
    }

    private Optional<TradeModels.Freeze> accountFreeze(long tradeId, long restrictionId) {
        return repository.activeFreezes(tradeId).stream()
                .filter(freeze -> freeze.source() == FreezeSource.ACCOUNT_BAN
                        && Objects.equals(freeze.sourceRef(), restrictionId)).findFirst();
    }

    private Set<Long> accountTradeIds(long accountId) {
        var ids = new TreeSet<>(repository.pendingTradeIdsForAccount(accountId));
        ids.addAll(repository.activeTradeIdsForAccount(accountId));
        return ids;
    }

    private LockPlan closurePlan(Collection<Long> tradeIds) {
        var accounts = new TreeSet<Long>();
        var resources = new TreeSet<LockPlan.Key>();
        for (long id : tradeIds) {
            var trade = repository.find(id).orElseThrow(Trade::notVisible);
            accounts.add(trade.buyerId());
            accounts.add(trade.sellerId());
            resources.add(tradeKey(id));
            conversations.find(id).ifPresent(conversationId -> resources.add(conversationKey(conversationId)));
        }
        return new LockPlan(sharedAccounts(accounts), resources);
    }

    private List<Trade> lockAffected(WriteTransaction transaction, LockPlan plan, Collection<Long> ids) {
        var needed = closurePlan(ids);
        if (!plan.accounts().keySet().containsAll(needed.accounts().keySet())) {
            throw new LockPlan.Changed(needed);
        }
        return ids.stream().sorted().map(id -> repository.lockTrade(transaction, id)).toList();
    }

    private Map<Long, Long> lockBranches(WriteTransaction transaction, Collection<Trade> trades) {
        var branches = new TreeMap<Long, Long>();
        for (var trade : trades) {
            branches.put(trade.id(), requireConversationId(trade.id()));
        }
        for (long branch : new TreeSet<>(branches.values())) {
            transaction.lock(conversationKey(branch), () -> conversations.lockConversation(transaction, branch));
        }
        return branches;
    }

    private void closeRequest(WriteTransaction transaction, Trade trade, long branch, CloseReason cause,
                              String reason, String basisRef, Set<Long> recipients, Instant now) {
        var closed = changed(trade, TradeStatus.CLOSED, null, cause.value(), null, now, null, now);
        repository.save(closed);
        UUID event = UUID.randomUUID();
        history(transaction, trade, closed, "request.close", ActorKind.SYSTEM, null, reason,
                basisRef, null, event, now);
        conversations.append(transaction, branch, event, "request_closed", "购买请求已关闭", null);
        archive(transaction, branch, trade.id(), cause.value());
        notify(transaction, trade, recipients, "trade.request_closed", event);
    }

    // ---------------------------------------------------------------- timeout task support

    public LockPlan timeoutPlan(long tradeId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var resources = new TreeSet<LockPlan.Key>();
        resources.add(tradeKey(trade.id()));
        conversations.find(tradeId).ifPresent(id -> resources.add(conversationKey(id)));
        return new LockPlan(Map.of(), resources);
    }

    public void lockForTimeout(WriteTransaction transaction, long tradeId) {
        repository.lockTrade(transaction, tradeId);
        requireConversation(transaction, tradeId);
    }

    public boolean timeoutApplicable(long tradeId, String sourceVersion) {
        var trade = repository.find(tradeId).orElse(null);
        if (trade == null || trade.status() != TradeStatus.IN_PROGRESS) {
            return false;
        }
        var wait = repository.waitFor(tradeId).orElse(null);
        if (wait == null || wait.ended() || !wait.active()) {
            return false;
        }
        if (!wait.fingerprint().equals(sourceVersion)) {
            return false;
        }
        if (!repository.activeFreezes(tradeId).isEmpty()) {
            return false;
        }
        return repository.currentConfirmations(tradeId).size() == 1;
    }

    public void applyTimeout(WriteTransaction transaction, ExecutionContext context, long tradeId,
                             String sourceVersion) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        if (!timeoutApplicable(tradeId, sourceVersion)) {
            return;
        }
        var now = now();
        var wait = repository.waitFor(tradeId).orElseThrow();
        if (wait.elapsedSeconds(now) < wait.waitSeconds()) {
            // The database clock has not reached the stored deadline yet; move the trigger forward.
            scheduleTimeout(tradeId, wait, now);
            return;
        }
        long caseId = cases.openTimeoutCase(transaction, context, tradeId, "单方确认超时");
        repository.insertFreeze(tradeId, FreezeSource.TIMEOUT, caseId, "单方确认超时", now);
        endWait(transaction, tradeId, WaitEndReason.TIMEOUT, now);
        var abnormal = changed(trade, TradeStatus.ABNORMAL, trade.activeAgreementId(), trade.closeReason(),
                trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
        repository.save(abnormal);
        long conversationId = requireConversationId(tradeId);
        UUID abnormalEvent = UUID.randomUUID();
        long abnormalHistory = history(transaction, trade, abnormal, "trade.abnormal", ActorKind.SYSTEM, null, "单方确认超时",
            "case:" + caseId, caseId, abnormalEvent, now);
        conversations.append(transaction, conversationId, abnormalEvent, "trade_abnormal",
                "单方确认超时，交易转异常", new ResourceRef("trade_transition", abnormalHistory));
        UUID frozenEvent = UUID.randomUUID();
        long frozenHistory = history(transaction, trade, abnormal, "trade.freeze", ActorKind.SYSTEM, null, "单方确认超时",
            "case:" + caseId, caseId, frozenEvent, now);
        conversations.append(transaction, conversationId, frozenEvent, "trade_frozen",
                "交易已冻结，等待管理员处理", new ResourceRef("trade_transition", frozenHistory));
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.timeout", abnormalEvent);
        audit(transaction, "trade.timeout", tradeId, new ResourceRef("case", caseId));
    }

    // ---------------------------------------------------------------- queries and read ports

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode getTrade(ExecutionContext context, long tradeId, List<String> include) {
        long viewer = actor(context);
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        trade.requireParticipant(viewer);
        var allowed = Set.of("agreement_history", "confirmation_history", "state_history");
        for (String value : include) {
            if (!allowed.contains(value)) {
                throw inputInvalid("include 参数无效");
            }
        }
        var node = view(tradeId, viewer, null);
        if (include.contains("agreement_history")) {
            views.agreements(node, limit(repository.agreements(tradeId)));
        }
        if (include.contains("confirmation_history")) {
            views.confirmations(node, limit(repository.confirmations(tradeId)));
        }
        if (include.contains("state_history")) {
            views.history(node, repository.history(tradeId, settings.historyLimit()));
        }
        return node;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode listMine(ExecutionContext context, String role, List<String> statusValues, Integer page,
                             Integer pageSize) {
        long viewer = actor(context);
        String normalizedRole = role == null || role.isBlank() ? "all" : role;
        if (!Set.of("all", "buyer", "seller").contains(normalizedRole)) {
            throw inputInvalid("role 参数无效");
        }
        int size = pageSize == null ? settings.pageSizeDefault() : pageSize;
        int number = page == null ? 1 : page;
        if (number < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw inputInvalid("分页参数无效");
        }
        var statuses = new ArrayList<TradeStatus>();
        for (String value : statusValues) {
            try {
                statuses.add(TradeStatus.from(value));
            } catch (IllegalArgumentException invalid) {
                throw inputInvalid("status 参数无效");
            }
        }
        var result = repository.pageForAccount(viewer, normalizedRole, statuses, size, (number - 1L) * size);
        var node = json.createObjectNode();
        var array = node.putArray("items");
        for (long id : result.ids()) {
            array.add(view(id, viewer, null));
        }
        node.put("page", number);
        node.put("page_size", size);
        node.put("total", result.total());
        return node;
    }

    @Override
    public TradeModels.ConversationAccess conversationAccess(long tradeId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        return new TradeModels.ConversationAccess(trade.buyerId(), trade.sellerId(), trade.status());
    }

    @Override
    public boolean pairFrozen(long firstAccountId, long secondAccountId) {
        return repository.pairFrozen(firstAccountId, secondAccountId);
    }

    public TradeModels.ReviewEligibility reviewEligibility(long tradeId, long reviewerId) {
        var found = repository.find(tradeId);
        if (found.isEmpty()) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, 0, false, "trade_not_found");
        }
        var trade = found.orElseThrow();
        if (!trade.isParticipant(reviewerId)) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, 0, false, "not_participant");
        }
        long reviewee = trade.buyerId() == reviewerId ? trade.sellerId() : trade.buyerId();
        if (trade.status() != TradeStatus.COMPLETED) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, reviewee, false, "trade_not_completed");
        }
        return new TradeModels.ReviewEligibility(tradeId, reviewerId, reviewee, true, "eligible");
    }

    // ---------------------------------------------------------------- internals

    private <R> WriteResult<JsonNode> run(ExecutionContext context, String operation, String key, R request,
                                          Prepare<R> planning,
                                          Qualify<R> qualification, Replay<R> replayCheck, Body<R> writer) {
        return writes.run(context, operation, key, request, new WriteExecutor.UseCase<R, Object>() {
            @Override
            public JsonNode digestInput(R input) {
                return json.valueToTree(input);
            }

            @Override
            public LockPlan prepare(ExecutionContext ctx, R input) {
                return planning.plan(ctx, input);
            }

            @Override
            public Object qualify(ExecutionContext ctx, R input, LockPlan plan) {
                return qualification.qualify(ctx, input);
            }

            @Override
            public void requireReplayAccess(ExecutionContext ctx, Object value, ResourceRef resource) {
                replayCheck.check(ctx, value, resource);
            }

            @Override
            public WriteResult.Response<?> write(WriteTransaction transaction, R input, Object value,
                                                 LockPlan plan) {
                return writer.write(transaction, input, value);
            }
        });
    }

    private LockPlan prepareCreate(long buyer, long productId) {
        var state = product.read(productId).orElseThrow(() -> productUnavailable());
        var accountsSet = new TreeSet<Long>(List.of(buyer, state.sellerId()));
        return new LockPlan(sharedAccounts(accountsSet), Set.of(productKey(productId)));
    }

    private LockPlan prepareAccept(long actor, long tradeId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var ids = new TreeSet<>(repository.pendingTradeIds(trade.productId(), tradeId));
        ids.add(tradeId);
        var accountsSet = new TreeSet<Long>(List.of(actor, trade.buyerId(), trade.sellerId()));
        var resources = new TreeSet<LockPlan.Key>();
        resources.add(productKey(trade.productId()));
        for (long id : ids) {
            resources.add(tradeKey(id));
            conversations.find(id).ifPresent(conversationId -> resources.add(conversationKey(conversationId)));
        }
        return new LockPlan(sharedAccounts(accountsSet), resources);
    }

    private LockPlan prepareTrade(long actor, long tradeId, boolean product, Long caseId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var accountsSet = new TreeSet<Long>(List.of(actor, trade.buyerId(), trade.sellerId()));
        var resources = new TreeSet<LockPlan.Key>();
        if (product) {
            resources.add(productKey(trade.productId()));
        }
        resources.add(tradeKey(tradeId));
        conversations.find(tradeId).ifPresent(id -> resources.add(conversationKey(id)));
        if (caseId != null) {
            resources.add(caseKey(caseId));
        }
        return new LockPlan(sharedAccounts(accountsSet), resources);
    }

    private LockPlan prepareGovernance(long manager, long tradeId, long caseId, boolean product) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var accountsSet = new TreeSet<Long>(List.of(manager, trade.buyerId(), trade.sellerId()));
        var resources = new TreeSet<LockPlan.Key>();
        if (product) {
            resources.add(productKey(trade.productId()));
        }
        resources.add(tradeKey(tradeId));
        resources.add(caseKey(caseId));
        conversations.find(tradeId).ifPresent(id -> resources.add(conversationKey(id)));
        return new LockPlan(sharedAccounts(accountsSet), resources);
    }

    private Void qualifyTrade(ExecutionContext context, long tradeId) {
        accounts.requireCurrentSession(context);
        repository.find(tradeId).orElseThrow(Trade::notVisible).requireParticipant(actor(context));
        return null;
    }

    private Void qualifyGovernance(ExecutionContext context, long tradeId) {
        accounts.requireCurrentSession(context);
        repository.find(tradeId).orElseThrow(Trade::notVisible);
        return null;
    }

    private void replayTrade(ExecutionContext context, Object qualification, ResourceRef resource) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT || resource == null
                || !"trade".equals(resource.type())) {
            return;
        }
        long actor = actor(context);
        var trade = repository.find(resource.id()).orElseThrow(Trade::notVisible);
        trade.requireParticipant(actor);
    }

    private void replayGovernance(ExecutionContext context, Object qualification, ResourceRef resource) {
        actor(context);
    }

    private Map<Long, LockPlan.AccountMode> sharedAccounts(Collection<Long> accountIds) {
        var map = new TreeMap<Long, LockPlan.AccountMode>();
        for (long id : accountIds) {
            map.put(id, LockPlan.AccountMode.SHARED);
        }
        return map;
    }

    private void requireWrite(long accountId) {
        var qualification = accounts.qualification(accountId);
        if (!qualification.exists()) {
            throw Trade.actionNotAllowed();
        }
        if (qualification.writeRestricted()) {
            throw new BusinessError("ACCOUNT_WRITE_RESTRICTED", 403, "账户当前受限");
        }
    }

    private Trade requireLockedTrade(WriteTransaction transaction, long caseId, long tradeId) {
        transaction.requireLocked(tradeKey(tradeId));
        transaction.requireLocked(caseKey(caseId));
        transaction.requireLocked(conversationKey(requireConversationId(tradeId)));
        return repository.find(tradeId).orElseThrow(Trade::notVisible);
    }

    private static void requireFreezable(Trade trade) {
        trade.requireNotTerminal();
        if (!trade.status().isActive()) {
            throw Trade.stateConflict();
        }
    }

    private Optional<TradePorts.CaseEnforcementOutcome> freezeFacts(WriteTransaction transaction, Trade trade,
                                                                    long caseId, long manager, String basisRef,
                                                                    String reason, Instant now, UUID eventId) {
        var active = repository.activeFreezes(trade.id());
        var existing = active.stream()
                .filter(freeze -> freeze.source() == FreezeSource.ADMIN_CASE
                        && Objects.equals(freeze.sourceRef(), caseId))
                .findFirst();
        if (existing.isPresent()) {
            var freeze = existing.orElseThrow();
            return repository.freezeTransition(freeze.id())
                    .filter(history -> exactAdminCaseFreeze(history, freeze, trade, caseId))
                    .map(TradeApplication::replayedFreeze);
        }
        boolean frozenBefore = !active.isEmpty();
        long freezeId = repository.insertFreeze(trade.id(), FreezeSource.ADMIN_CASE, caseId, reason, now);
        pauseWait(transaction, trade.id(), now);
        repository.touch(trade.id(), now);
        long historyId = historyFreeze(transaction, trade, "trade.freeze", ActorKind.ADMIN, manager, reason,
                basisRef, caseId, freezeId, frozenBefore, true, eventId, now);
        return Optional.of(new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                trade.status().value(), phase(trade.phase()), phase(trade.phase()), frozenBefore, true, false));
    }

    private TradePorts.CaseEnforcementOutcome liftFreezeFacts(WriteTransaction transaction, Trade trade,
                                                              TradeModels.Freeze freeze, long caseId, long manager,
                                                              String basisRef, String reason, Instant now,
                                                              UUID eventId) {
        repository.endFreeze(freeze.id(), manager, now);
        repository.touch(trade.id(), now);
        resumeWaitIfPossible(transaction, trade, now);
        boolean frozenAfter = !repository.activeFreezes(trade.id()).isEmpty();
        long historyId = historyFreeze(transaction, trade, "trade.unfreeze", ActorKind.ADMIN, manager, reason,
                basisRef, caseId, freeze.id(), true, frozenAfter, eventId, now);
        return new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                trade.status().value(), phase(trade.phase()), phase(trade.phase()), true, frozenAfter, false);
    }

    private TradePorts.CaseEnforcementOutcome adjustStatusFacts(WriteTransaction transaction, Trade trade,
                                                                TradePorts.ProductState state, TradeStatus target,
                                                                long caseId, long manager, String basisRef,
                                                                String reason, Instant now, UUID eventId) {
        if (state.productId() != trade.productId()) {
            throw Trade.stateConflict();
        }
        boolean frozenBefore = !repository.activeFreezes(trade.id()).isEmpty();
        TerminalReason terminalReason = target == TradeStatus.COMPLETED
                ? TerminalReason.COMPLETED : TerminalReason.ADMIN_TERMINATED;
        var ended = changed(trade, target, trade.activeAgreementId(), null, terminalReason.value(),
                trade.respondedAt(), now, now);
        repository.save(ended);
        endWait(transaction, trade.id(), target == TradeStatus.COMPLETED
                ? WaitEndReason.COMPLETED : WaitEndReason.TERMINATED, now);
        endFreezes(transaction, trade.id(), now);
        repository.terminateOpenDisputes(trade.id(), now);
        product.release(transaction, state, trade.id(), "admin_terminated");
        long historyId = historyAgreement(transaction, trade, ended,
                target == TradeStatus.COMPLETED ? "trade.completed" : "trade.terminated", ActorKind.ADMIN,
                manager, reason, basisRef, caseId, trade.activeAgreementId(), null, eventId, now);
        return new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                target.value(), phase(trade.phase()), phase(ended.phase()), frozenBefore, false, false);
    }

    private TradePorts.CaseEnforcementOutcome restoreFacts(WriteTransaction transaction, Trade trade, long caseId,
                                                           long manager, String basisRef, String reason, Instant now,
                                                           UUID eventId) {
        boolean frozen = !repository.activeFreezes(trade.id()).isEmpty();
        repository.invalidateConfirmations(trade.id(), InvalidationReason.ADMIN_RESTORED, now);
        endWait(transaction, trade.id(), WaitEndReason.ADMIN_RESTORED, now);
        var restored = changed(trade, TradeStatus.IN_PROGRESS, trade.activeAgreementId(),
                trade.closeReason(), trade.terminalReason(), trade.respondedAt(), trade.endedAt(), now);
        repository.save(restored);
        long historyId = historyAgreement(transaction, trade, restored, "trade.restore", ActorKind.ADMIN,
                manager, reason, basisRef, caseId, trade.activeAgreementId(), null, eventId, now);
        return new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                TradeStatus.IN_PROGRESS.value(), phase(trade.phase()), phase(restored.phase()), frozen, frozen,
                false);
    }

    private static boolean exactAdminCaseFreeze(TradeModels.History history, TradeModels.Freeze freeze, Trade trade,
                                                long caseId) {
        return "trade.freeze".equals(history.action())
                && history.tradeId() == trade.id()
                && Objects.equals(history.caseId(), caseId)
                && history.actorKind() == ActorKind.ADMIN
                && history.freezeId() != null
                && history.freezeId() == freeze.id()
                && freeze.tradeId() == trade.id()
                && freeze.source() == FreezeSource.ADMIN_CASE
                && Objects.equals(freeze.sourceRef(), caseId)
                && freeze.active();
    }

    private static TradePorts.CaseEnforcementOutcome replayedFreeze(TradeModels.History history) {
        return new TradePorts.CaseEnforcementOutcome(history.tradeId(), history.id(), history.businessEventId(),
                history.fromStatus(), history.toStatus(), history.fromPhase(), history.toPhase(),
                Boolean.TRUE.equals(history.fromFrozen()), Boolean.TRUE.equals(history.toFrozen()), true);
    }

    private TradePorts.ProductState lockProduct(WriteTransaction transaction, long productId) {
        var result = new java.util.concurrent.atomic.AtomicReference<TradePorts.ProductState>();
        transaction.lock(productKey(productId), () -> result.set(product.lock(transaction, productId)));
        if (result.get() == null) {
            throw productUnavailable();
        }
        return result.get();
    }

    private void lockCase(WriteTransaction transaction, long caseId, long manager, long tradeId, String basisRef) {
        transaction.lock(caseKey(caseId), () -> cases.lockAndValidate(transaction, caseId, manager, tradeId, basisRef));
    }

    private long requireConversation(WriteTransaction transaction, long tradeId) {
        long conversationId = requireConversationId(tradeId);
        transaction.lock(conversationKey(conversationId),
                () -> conversations.lockConversation(transaction, conversationId));
        return conversationId;
    }

    private long requireConversationId(long tradeId) {
        return conversations.find(tradeId).orElseThrow(() -> new BusinessError(
                "TRADE_CONVERSATION_NOT_FOUND", 409, "交易会话不存在"));
    }

    private void archive(WriteTransaction transaction, long conversationId, long tradeId, String reason) {
        conversations.archive(transaction, conversationId, tradeId, reason);
    }

    private void pauseWait(WriteTransaction transaction, long tradeId, Instant now) {
        var wait = repository.waitFor(tradeId).orElse(null);
        if (wait != null && wait.active()) {
            repository.saveWait(tradeId, wait.pause(now));
        }
    }

    private void resumeWaitIfPossible(WriteTransaction transaction, Trade trade, Instant now) {
        if (trade.status() != TradeStatus.IN_PROGRESS || !repository.activeFreezes(trade.id()).isEmpty()) {
            return;
        }
        var wait = repository.waitFor(trade.id()).orElse(null);
        if (wait == null || wait.ended() || !wait.paused()) {
            return;
        }
        if (repository.currentConfirmations(trade.id()).isEmpty()) {
            return;
        }
        var resumed = wait.resume(now);
        repository.saveWait(trade.id(), resumed);
        scheduleTimeout(trade.id(), resumed, now);
    }

    private void endWait(WriteTransaction transaction, long tradeId, WaitEndReason reason, Instant now) {
        var wait = repository.waitFor(tradeId).orElse(null);
        if (wait != null && !wait.ended()) {
            repository.saveWait(tradeId, wait.end(now, reason));
        }
    }

    private void endFreezes(WriteTransaction transaction, long tradeId, Instant now) {
        repository.endAllFreezes(tradeId, now);
    }

    private void scheduleTimeout(long tradeId, TradeModels.Wait wait, Instant now) {
        var deadline = wait.deadline(now);
        String trigger = tradeId + ":" + wait.startedAt().toEpochMilli() + ":"
                + (wait.activeSince() == null ? "paused" : wait.activeSince().toEpochMilli()) + ":"
                + deadline.toEpochMilli();
        schedules.schedule(new TaskSchedules.Spec(TradeTimeoutHandler.KIND, new ResourceRef("trade", tradeId),
                trigger, wait.fingerprint(), deadline, wait.policyVersion()));
    }

    private Trade changed(Trade trade, TradeStatus status, Long activeAgreementId, String closeReason,
                          String terminalReason, Instant respondedAt, Instant endedAt, Instant now) {
        if (status != trade.status()) {
            trade.status().requireTransition(status);
        }
        return new Trade(trade.id(), trade.productId(), trade.buyerId(), trade.sellerId(), status,
                trade.requestNote(), activeAgreementId, trade.version() + 1, closeReason, terminalReason,
                trade.requestedAt(), respondedAt, endedAt, trade.createdAt(), now);
    }

    private long history(WriteTransaction transaction, Trade before, Trade after, String action, ActorKind actorKind,
                         Long actorId, String reason, String basisRef, Long caseId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                null, null, null, null, null, null, null, eventId, now);
    }

    private long historyAgreement(WriteTransaction transaction, Trade before, Trade after, String action,
                                  ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                                  Long agreementId, Long agreementDecisionId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                agreementId, agreementDecisionId, null, null, null, null, null, eventId, now);
    }

    private long historyConfirmation(WriteTransaction transaction, Trade before, Trade after, String action,
                                     ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                                     Long agreementId, Long confirmationId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                agreementId, null, confirmationId, null, null, null, null, eventId, now);
    }

    private long historyCancellation(WriteTransaction transaction, Trade before, Trade after, String action,
                                     ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                                     Long cancellationId, Long cancellationDecisionId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                null, null, null, cancellationId, cancellationDecisionId, null, null, eventId, now);
    }

    private long historyDispute(WriteTransaction transaction, Trade before, Trade after, String action,
                                ActorKind actorKind, Long actorId, String reason, String basisRef, Long caseId,
                                Long disputeId, Long resolutionConfirmationId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                null, null, null, null, null, disputeId, resolutionConfirmationId, eventId, now);
    }

    private long historyDisputeAgreement(WriteTransaction transaction, Trade before, Trade after, String action,
                                         ActorKind actorKind, Long actorId, String reason, String basisRef,
                                         Long caseId, Long agreementId, Long disputeId, UUID eventId, Instant now) {
        return history(transaction, before, after, action, actorKind, actorId, reason, basisRef, caseId,
                agreementId, null, null, null, null, disputeId, null, eventId, now);
    }

    private long history(WriteTransaction transaction, Trade before, Trade after, String action, ActorKind actorKind,
                         Long actorId, String reason, String basisRef, Long caseId, Long agreementId,
                         Long agreementDecisionId, Long confirmationId, Long cancellationId,
                         Long cancellationDecisionId, Long disputeId, Long resolutionConfirmationId, UUID eventId,
                         Instant now) {
        String fromStatus = before.status() == after.status() ? null : before.status().value();
        String toStatus = before.status() == after.status() ? null : after.status().value();
        var beforePhase = before.phase();
        var afterPhase = after.phase();
        String fromPhase = beforePhase == afterPhase ? null : phase(beforePhase);
        String toPhase = beforePhase == afterPhase ? null : phase(afterPhase);
        return repository.insertHistory(new TradeModels.History(0, before.id(), action, fromStatus, toStatus,
                fromPhase, toPhase, actorKind, actorId, reason, basisRef, caseId, null, null, null, agreementId,
                agreementDecisionId, confirmationId, cancellationId, cancellationDecisionId, disputeId,
                resolutionConfirmationId, eventId, now));
    }

    /**
     * Records a freeze transition with its exact freeze association and a status snapshot. The
     * snapshot is only exposed through the case-subject result; the public history projection keeps
     * suppressing unchanged from/to values.
     */
    private long historyFreeze(WriteTransaction transaction, Trade trade, String action, ActorKind actorKind,
                               Long actorId, String reason, String basisRef, Long caseId, long freezeId,
                               boolean frozenBefore, boolean frozenAfter, UUID eventId, Instant now) {
        String status = trade.status().value();
        String tradePhase = phase(trade.phase());
        return repository.insertHistory(new TradeModels.History(0, trade.id(), action, status, status,
                tradePhase, tradePhase, actorKind, actorId, reason, basisRef, caseId, freezeId, frozenBefore,
                frozenAfter, null, null, null, null, null, null, null, eventId, now));
    }

    private static String phase(TradePhase phase) {
        return phase == null ? null : phase.value();
    }

    private void notify(WriteTransaction transaction, Trade trade, Set<Long> recipients, String eventType,
                        UUID businessEventId) {
        // S1 event types are underscore identifiers; business vocabulary uses dotted names elsewhere.
        notifications.register(transaction, businessEventId, eventType, trade.id(), recipients);
    }

    private void audit(WriteTransaction transaction, String action, long tradeId,
                       ResourceRef basis) {
        transaction.audit(action, new ResourceRef("trade", tradeId), basis, object("audit")
                .put("trade_id", tradeId));
    }

    private ObjectNode view(long tradeId, long viewer, Long knownConversationId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var snapshot = repository.snapshot(tradeId).orElse(null);
        var current = repository.currentAgreement(tradeId).orElse(null);
        var pending = repository.pendingAgreement(tradeId).orElse(null);
        var confirmations = repository.currentConfirmations(tradeId);
        var wait = repository.waitFor(tradeId).orElse(null);
        var freezes = repository.activeFreezes(tradeId);
        var cancellation = repository.pendingCancellation(tradeId).orElse(null);
        var dispute = repository.openDispute(tradeId).orElse(null);
        var profiles = accounts.profiles(Set.of(trade.buyerId(), trade.sellerId()));
        Long conversationId = knownConversationId != null ? knownConversationId : requireConversationId(tradeId);
        var summary = snapshot == null ? product.visibleSummary(trade.productId(), viewer).orElse(null) : null;
        var qualification = accounts.qualification(viewer);
        return views.view(trade, snapshot, summary, current, pending, confirmations, wait, freezes,
                cancellation, dispute, conversationId, profiles, viewer,
                qualification.exists() && !qualification.writeRestricted(), now());
    }

    private ObjectNode agreementEnvelope(TradeModels.Agreement agreement, long tradeId, long viewer) {
        var node = json.createObjectNode();
        node.set("agreement", views.agreementItem(agreement));
        node.set("trade", view(tradeId, viewer, null));
        return node;
    }

    private ObjectNode confirmationEnvelope(TradeModels.Confirmation confirmation, long tradeId, long viewer) {
        var node = json.createObjectNode();
        node.set("confirmation", views.confirmationRecord(confirmation));
        node.set("trade", view(tradeId, viewer, null));
        return node;
    }

    private TradePorts.GovernanceOutcome governanceOutcome(long tradeId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        return new TradePorts.GovernanceOutcome(trade.id(), trade.status().value(),
                trade.phase() == null ? null : trade.phase().value(), trade.version(), trade.terminalReason());
    }

    private ObjectNode governanceView(TradePorts.GovernanceOutcome outcome) {
        var node = json.createObjectNode();
        node.put("trade_id", Long.toString(outcome.tradeId()));
        node.put("status", outcome.status());
        node.put("phase", outcome.phase());
        node.put("version", outcome.version());
        node.put("terminal_reason", outcome.terminalReason());
        return node;
    }

    private <T> List<T> limit(List<T> values) {
        return values.size() <= settings.historyLimit() ? values : values.subList(0, settings.historyLimit());
    }

    private static TradeModels.Agreement withId(TradeModels.Agreement agreement, long id) {
        return new TradeModels.Agreement(id, agreement.tradeId(), agreement.baseAgreementId(), agreement.versionNo(),
                agreement.status(), agreement.proposedBy(), agreement.deliveryAt(), agreement.deliveryPlaceText(),
                agreement.deliveryMethod(), agreement.amountCents(), agreement.paymentMethod(),
                agreement.paymentTiming(), agreement.proposedAt(), agreement.businessEventId());
    }

    private static TradeModels.Cancellation withId(TradeModels.Cancellation cancellation, long id) {
        return new TradeModels.Cancellation(id, cancellation.tradeId(), cancellation.proposedBy(),
                cancellation.mode(), cancellation.reason(), cancellation.status(), cancellation.proposedAt(),
                cancellation.businessEventId());
    }

    private static TradeModels.Confirmation withId(TradeModels.Confirmation confirmation, long id) {
        return new TradeModels.Confirmation(id, confirmation.tradeId(), confirmation.agreementId(),
                confirmation.confirmerId(), confirmation.note(), confirmation.submittedAt(),
                confirmation.invalidatedAt(), confirmation.invalidationReason(), confirmation.businessEventId());
    }

    private void requireRequestOpen(Trade trade) {
        if (trade.status().isTerminal()) {
            throw new BusinessError("TRADE_TERMINAL", 409, "交易已结束");
        }
        if (trade.status().isEndedRequest()) {
            throw new BusinessError("REQUEST_ALREADY_ENDED", 409, "请求已结束");
        }
        if (trade.status() != TradeStatus.PENDING_ACCEPTANCE) {
            throw Trade.stateConflict();
        }
    }

    private void requireCancellable(Trade trade) {
        if (trade.status() == TradeStatus.ABNORMAL) {
            throw new BusinessError("STATE_CONFLICT", 409, "异常交易需管理员处理");
        }
        if (trade.status() != TradeStatus.IN_PROGRESS && trade.status() != TradeStatus.DISPUTED) {
            throw Trade.stateConflict();
        }
    }

    private void requireNotFrozen(WriteTransaction transaction, long tradeId) {
        if (!repository.activeFreezes(tradeId).isEmpty()) {
            throw new BusinessError("TRADE_FROZEN", 409, "交易已冻结");
        }
    }

    private long actor(ExecutionContext context) {
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new IllegalStateException("Account execution context required");
        }
        return Long.parseLong(context.actorId());
    }

    private long other(Trade trade, long accountId) {
        return trade.buyerId() == accountId ? trade.sellerId() : trade.buyerId();
    }

    private static Decision decision(String value) {
        try {
            return Decision.from(value);
        } catch (RuntimeException invalid) {
            throw inputInvalid("decision 参数无效");
        }
    }

    private static TradeStatus terminalTarget(String value) {
        TradeStatus target;
        try {
            target = TradeStatus.from(value);
        } catch (RuntimeException invalid) {
            throw inputInvalid("target_status 参数无效");
        }
        if (target != TradeStatus.COMPLETED && target != TradeStatus.TERMINATED) {
            throw new BusinessError("TRANSITION_NOT_ALLOWED", 409, "目标状态不可调整");
        }
        return target;
    }

    private static BusinessError restoreNotAllowed() {
        return new BusinessError("TRANSITION_NOT_ALLOWED", 409, "仅异常交易可恢复");
    }

    private static BusinessError freezeNotActive() {
        return new BusinessError("TRADE_FREEZE_NOT_ACTIVE", 409, "冻结不存在或已解除");
    }

    private Instant now() {
        return clock == null ? repository.databaseNow() : clock.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private ObjectNode object(String action) {
        return json.createObjectNode().put("action", action);
    }

    private static BusinessError inputInvalid(String message) {
        return new BusinessError("INPUT_INVALID", 422, message);
    }

    private static BusinessError versionConflict() {
        return new BusinessError("VERSION_CONFLICT", 409, "版本已变化");
    }

    private static BusinessError productUnavailable() {
        return new BusinessError("PRODUCT_NOT_AVAILABLE", 409, "商品当前不可交易");
    }

    private static String requiredText(String value, int max, String field) {
        if (value == null || value.isBlank() || value.length() > max) {
            throw inputInvalid(field + "不能为空且长度不能超过" + max);
        }
        return value.trim();
    }

    private static String optionalText(String value, int max, String field) {
        if (value == null) {
            return null;
        }
        if (value.length() > max) {
            throw inputInvalid(field + "长度不能超过" + max);
        }
        return value.isBlank() ? null : value.trim();
    }

    private static LockPlan.Key productKey(long productId) {
        return new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(productId));
    }

    private static LockPlan.Key tradeKey(long tradeId) {
        return new LockPlan.Key(LockPlan.Domain.TRADE, List.of(tradeId));
    }

    private static LockPlan.Key caseKey(long caseId) {
        return new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId));
    }

    private static LockPlan.Key conversationKey(long conversationId) {
        return new LockPlan.Key(LockPlan.Domain.TRADE_CONVERSATION, List.of(conversationId));
    }

    private Void qualifySession(ExecutionContext context) {
        accounts.requireCurrentSession(context);
        return null;
    }

    @FunctionalInterface
    private interface Prepare<R> {
        LockPlan plan(ExecutionContext context, R request);
    }

    @FunctionalInterface
    private interface Qualify<R> {
        Object qualify(ExecutionContext context, R request);
    }

    @FunctionalInterface
    private interface Replay<R> {
        void check(ExecutionContext context, Object qualification, ResourceRef resource);
    }

    @FunctionalInterface
    private interface Body<R> {
        WriteResult.Response<?> write(WriteTransaction transaction, R request, Object qualification);
    }
}
