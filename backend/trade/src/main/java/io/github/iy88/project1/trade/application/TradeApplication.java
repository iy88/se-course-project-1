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
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary.ActorKind;
import io.github.iy88.project1.trade.domain.TradeVocabulary.AgreementStatus;
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
    private final TradeHistoryWriter historyWriter;
    private final TradeViews views;
    private final TradeQueries queries;
    private final TradeGovernancePlanning governancePlanning;
    private final TradeCancellation cancellation;
    private final WriteExecutor writes;
    private final TaskSchedules schedules;
    private final Clock clock;
    private final TradePorts.Product product;
    private final TradePorts.Accounts accounts;
    private final TradePorts.Conversation conversations;
    private final TradePorts.Cases cases;
    private final TradePorts.Notifications notifications;
    private final JsonMapper json;
    private final TradeReviews reviews;
    private final TradeDisputes disputes;
    private final TradeConfirmation confirmation;
    private final TradeConfirmationTimeout timeout;

    public TradeApplication(TradeRepository repository, WriteExecutor writes, TaskSchedules schedules, Clock clock,
                            TradeSettings settings, TradePorts.Product product, TradePorts.Accounts accounts,
                            TradePorts.Conversation conversations, TradePorts.Cases cases,
                            TradePorts.Notifications notifications, JsonMapper json) {
        this.repository = repository;
        this.historyWriter = new TradeHistoryWriter(repository);
        this.views = new TradeViews(json);
        this.writes = writes;
        this.schedules = schedules;
        this.clock = clock;
        this.product = product;
        this.accounts = accounts;
        this.conversations = conversations;
        this.cases = cases;
        this.notifications = notifications;
        this.json = json;
        this.reviews = new TradeReviews(repository, views, accounts, settings, json, clock);
        this.queries = new TradeQueries(repository, views, accounts, product, conversations, settings, json, clock);
        this.governancePlanning = new TradeGovernancePlanning(repository, conversations, queries);
        this.confirmation = new TradeConfirmation(repository, historyWriter, views, queries, accounts, product,
                conversations, notifications, schedules, settings, clock, json);
        this.cancellation = new TradeCancellation(repository, historyWriter, views, queries, accounts,
                conversations, notifications, product, clock, json);
        this.disputes = new TradeDisputes(repository, historyWriter, views, queries, accounts, conversations,
                cases, clock, json);
        this.timeout = new TradeConfirmationTimeout(repository, historyWriter, queries, schedules, clock,
                conversations, cases, notifications, json);
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
                    // A new purchase has no trade row yet, so per-trade requireNotFrozen cannot see
                    // a freeze from another trade of either party. Read the party-level fact under
                    // the account locks already held by this write.
                    requireNoActivePartyFreeze(buyer);
                    requireNoActivePartyFreeze(preview.sellerId());
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
                    repository.insertPurchaseProductSnapshot(tradeId, state.contentVersion(), state.title(),
                            state.description(), state.priceCents(), now);
                    long conversationId = conversations.ensure(transaction, tradeId, state.productId(),
                            buyer, state.sellerId());
                    var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
                    UUID eventId = UUID.randomUUID();
                    long transitionId = historyWriter.history(transaction,
                            trade, trade, "request.create", ActorKind.BUYER, buyer, note, null, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "request_created",
                            "买方提交了购买请求", new ResourceRef("trade_transition", transitionId));
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
                    long transitionId = historyWriter.history(transaction,
                            trade, accepted, "request.accept", ActorKind.SELLER, seller, null, null, null, acceptedEvent, now);
                    conversations.append(transaction, conversationId, acceptedEvent, "request_accepted",
                            "卖方已接受购买请求", new ResourceRef("trade_transition", transitionId));
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
                    long transitionId = historyWriter.history(transaction,
                            trade, rejected, "request.reject", ActorKind.SELLER, seller, reason, null, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "request_rejected",
                            "卖方拒绝了购买请求", new ResourceRef("trade_transition", transitionId));
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
                    long transitionId = historyWriter.history(transaction,
                            trade, withdrawn, "request.withdraw", ActorKind.BUYER, buyer, null, null, null, eventId, now);
                    conversations.append(transaction, conversationId, eventId, "request_withdrawn",
                            "买方撤回了购买请求", new ResourceRef("trade_transition", transitionId));
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
                    historyWriter.historyAgreement(transaction, trade, updated,
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
                    historyWriter.historyAgreement(transaction, trade, updated, "agreement." + decision.value(),
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
                (transaction, request, qualification) -> confirmation.submit(transaction, actor, request));
    }

    // ---------------------------------------------------------------- cancellation

    public WriteResult<JsonNode> proposeCancellation(ExecutionContext context, String key,
                                                     TradeCommands.ProposeCancellation command) {
        long actor = actor(context);
        return run(context, "trade.cancellation.propose", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), true, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> cancellation.propose(transaction, actor, request));
    }

    public WriteResult<JsonNode> decideCancellation(ExecutionContext context, String key,
                                                    TradeCommands.DecideCancellation command) {
        long actor = actor(context);
        return run(context, "trade.cancellation.decide", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), true, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> cancellation.decide(transaction, actor, request));
    }

    // ---------------------------------------------------------------- reviews

    public WriteResult<JsonNode> submitReview(ExecutionContext context, String key, TradeCommands.SubmitReview command) {
        actor(context);
        return writes.run(context, "trade.review.submit", key, command, reviews);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode getTradeReviews(ExecutionContext context, long tradeId) {
        return reviews.getTradeReviews(context, tradeId);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode listMyReviews(ExecutionContext context, String direction, Integer page, Integer pageSize) {
        return reviews.listMyReviews(context, direction, page, pageSize);
    }

    // ---------------------------------------------------------------- disputes

    public WriteResult<JsonNode> openDispute(ExecutionContext context, String key,
                                             TradeCommands.OpenDispute command) {
        long actor = actor(context);
        return run(context, "trade.dispute.open", key, command,
                (ctx, request) -> prepareTrade(actor, request.tradeId(), false, null),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> disputes.openDispute(context, transaction, request));
    }

    public WriteResult<JsonNode> confirmResolution(ExecutionContext context, String key,
                                                   TradeCommands.ConfirmResolution command) {
        long actor = actor(context);
        return run(context, "trade.dispute.resolve", key, command,
                (ctx, request) -> disputes.prepareConfirmResolution(actor, request.tradeId(), request.disputeId()),
                (ctx, request) -> qualifyTrade(ctx, request.tradeId()),
                this::replayTrade,
                (transaction, request, qualification) -> disputes.confirmResolution(context, transaction, request));
    }

    // ---------------------------------------------------------------- governance commands

    public WriteResult<JsonNode> freeze(ExecutionContext context, String key, TradeCommands.Freeze command) {
        long manager = actor(context);
        return run(context, "trade.freeze", key, command,
                (ctx, request) -> governancePlanning.freezeChange(manager, request.tradeId(), request.caseId()),
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
        return governancePlanning.governance(managerId, tradeId, caseId, product);
    }

    @Override
    public TradePorts.CaseEnforcementPlan prepare(long managerId, long tradeId, long caseId, boolean product) {
        return governancePlanning.enforcement(managerId, tradeId, caseId, product);
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
    public void lockTradeRow(WriteTransaction transaction, long tradeId) {
        repository.lockTradeRow(tradeId);
    }

    @Override
    public void lockConversationRow(WriteTransaction transaction, long conversationId) {
        conversations.lockConversationRow(transaction, conversationId);
    }

    @Override
    public void lockCaseProductRow(WriteTransaction transaction, long productId) {
        if (product.lock(transaction, productId) == null) {
            throw productUnavailable();
        }
    }

    @Override
    public TradePorts.CaseEnforcementOutcome freezeLocked(WriteTransaction transaction, long caseId, long tradeId,
                                                          String basisRef, String reason) {
        var trade = requireLockedTrade(transaction, caseId, tradeId);
        long manager = actor(transaction.context());
        String validatedReason = requiredText(reason, 500, "冻结原因");
        requireWrite(manager);
        requirePartyFreezeLocks(transaction, trade);
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
        requirePartyFreezeLocks(transaction, trade);
        requireFreezable(trade);
        lockCase(transaction, caseId, manager, trade.id(), basisRef);
        long conversationId = requireConversation(transaction, trade.id());
        UUID eventId = UUID.randomUUID();
        var outcome = freezeFacts(transaction, trade, caseId, manager, basisRef, validatedReason, now(), eventId);
        outcome.filter(frozen -> !frozen.alreadyEffective()).ifPresent(frozen ->
                publishFreeze(transaction, trade, conversationId, caseId, eventId, frozen));
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> liftFreeze(ExecutionContext context, String key,
                                            TradeCommands.LiftFreeze command) {
        long manager = actor(context);
        return run(context, "trade.freeze.lift", key, command,
                (ctx, request) -> governancePlanning.freezeChange(manager, request.tradeId(), request.caseId()),
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
        requirePartyFreezeLocks(transaction, trade);
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
    public TradePorts.CaseEnforcementOutcome liftCaseFreezeLocked(WriteTransaction transaction, long caseId,
                                                                  long tradeId, String basisRef, String reason) {
        var trade = requireLockedTrade(transaction, caseId, tradeId);
        long manager = actor(transaction.context());
        String validatedReason = requiredText(reason, 500, "解除原因");
        requireWrite(manager);
        requirePartyFreezeLocks(transaction, trade);
        if (trade.status().isTerminal()) {
            throw freezeNotActive();
        }
        var freeze = caseSourcedFreeze(trade, caseId);
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
        requirePartyFreezeLocks(transaction, trade);
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
        publishLift(transaction, trade, conversationId, caseId, eventId, outcome);
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> adjustStatus(ExecutionContext context, String key,
                                              TradeCommands.AdjustStatus command) {
        long manager = actor(context);
        return run(context, "trade.adjust", key, command,
                (ctx, request) -> governancePlanning.governance(manager, request.tradeId(), request.caseId(), true),
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
        publishAdjust(transaction, trade, conversationId, caseId, eventId, target, outcome.transitionRef());
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> restore(ExecutionContext context, String key, TradeCommands.Restore command) {
        long manager = actor(context);
        return run(context, "trade.restore", key, command,
                (ctx, request) -> governancePlanning.governance(manager, request.tradeId(), request.caseId(), false),
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
    public void publishLocked(WriteTransaction transaction, long caseId, long tradeId, String action,
                              TradePorts.CaseEnforcementOutcome outcome, String reason) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        long conversationId = requireConversationId(tradeId);
        switch (action) {
            case "freeze_trade" -> {
                if (!outcome.alreadyEffective()) {
                    publishFreeze(transaction, trade, conversationId, caseId, outcome.businessEventId(), outcome);
                }
            }
            case "lift_trade_freeze" ->
                    publishLift(transaction, trade, conversationId, caseId, outcome.businessEventId(), outcome);
            case "adjust_trade_status" -> publishAdjust(transaction, trade, conversationId, caseId,
                    outcome.businessEventId(), TradeStatus.from(outcome.currentStatus()), outcome.transitionRef());
            case "restore_trade" ->
                    publishRestore(transaction, trade, conversationId, caseId, outcome.businessEventId(), outcome);
            default -> throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该处置动作没有交易发布逻辑");
        }
    }

    @Override
    public long legacyFreezeTransition(long caseId, long tradeId) {
        var transitions = repository.adminCaseFreezeTransitions(caseId, tradeId);
        if (transitions.size() != 1) {
            throw freezeNotActive();
        }
        return transitions.getFirst();
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
        publishRestore(transaction, trade, conversationId, caseId, eventId, outcome);
        return governanceOutcome(trade.id());
    }


    public WriteResult<JsonNode> resolveDisputeAsAdmin(ExecutionContext context, String key,
                                                       TradeCommands.ResolveDispute command) {
        long manager = actor(context);
        return run(context, "trade.dispute.admin_resolve", key, command,
                (ctx, request) -> {
                    var dispute = repository.dispute(request.disputeId())
                            .orElseThrow(() -> new BusinessError("DISPUTE_NOT_OPEN", 409, "争议不存在"));
                    return governancePlanning.governance(manager, dispute.tradeId(), request.caseId(), false);
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
        repository.find(found.tradeId()).orElseThrow(Trade::notVisible);
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
        long historyId = historyWriter.historyDisputeAgreement(transaction, trade, restored, "dispute.resolve",
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
        // An account ban freezes every affected trade for both parties (BR-33). Taking the
        // exclusive party locks makes product/new-trade qualification reads observe the freeze
        // before they can start, not only the banned account's own qualification.
        return closurePlan(accountTradeIds(accountId), LockPlan.AccountMode.EXCLUSIVE);
    }

    @Override
    public int closePendingForProduct(WriteTransaction transaction, LockPlan plan, long productId,
                                       CloseReason reason, String basisRef) {
        var trades = lockAffected(transaction, plan, repository.pendingTradeIdsForProduct(productId)).stream()
                .filter(trade -> trade.status() == TradeStatus.PENDING_ACCEPTANCE).toList();
        var branches = lockBranches(transaction, trades);
        return closePending(transaction, trades, branches, reason, basisRef, now());
    }

    @Override
    public int closePendingForProductLocked(WriteTransaction transaction, long productId,
                                            CloseReason reason, String basisRef) {
        var trades = acquiredTrades(transaction, repository.pendingTradeIdsForProduct(productId)).stream()
                .filter(trade -> trade.status() == TradeStatus.PENDING_ACCEPTANCE).toList();
        var branches = acquiredBranches(transaction, trades);
        return closePending(transaction, trades, branches, reason, basisRef, now());
    }

    @Override
    public void applyAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                                long restrictionId, String reason, String basisRef) {
        var trades = lockAffected(transaction, plan, accountTradeIds(accountId)).stream()
                .filter(TradeApplication::accountBanCandidate).toList();
        var branches = lockBranches(transaction, trades);
        applyAccountBan(transaction, restrictionId, reason, basisRef, trades, branches, now());
    }

    @Override
    public int applyAccountBanLocked(WriteTransaction transaction, long accountId, long restrictionId,
                                     String reason, String basisRef) {
        transaction.requireExclusiveAccount(accountId);
        var trades = acquiredTrades(transaction, accountTradeIds(accountId)).stream()
                .filter(TradeApplication::accountBanCandidate).toList();
        var branches = acquiredBranches(transaction, trades);
        return applyAccountBan(transaction, restrictionId, reason, basisRef, trades, branches, now());
    }

    @Override
    public void removeAccountBan(WriteTransaction transaction, LockPlan plan, long accountId,
                                 long restrictionId, String basisRef) {
        var trades = lockAffected(transaction, plan, repository.activeTradeIdsForAccount(accountId)).stream()
                .filter(trade -> trade.status().isActive()).toList();
        var branches = lockBranches(transaction, trades);
        removeAccountBan(transaction, restrictionId, basisRef, trades, branches, now());
    }

    @Override
    public int removeAccountBanLocked(WriteTransaction transaction, long accountId, long restrictionId,
                                      String basisRef) {
        transaction.requireExclusiveAccount(accountId);
        var trades = acquiredTrades(transaction, repository.activeTradeIdsForAccount(accountId)).stream()
                .filter(trade -> trade.status().isActive()).toList();
        var branches = acquiredBranches(transaction, trades);
        return removeAccountBan(transaction, restrictionId, basisRef, trades, branches, now());
    }

    @Override
    public boolean hasActivePartyFreeze(long accountId) {
        return repository.hasActivePartyFreeze(accountId);
    }

    @Override
    public boolean hasActiveAccountFreeze(long accountId) {
        return repository.activeTradeIdsForAccount(accountId).stream()
                .anyMatch(tradeId -> !repository.activeFreezes(tradeId).isEmpty());
    }

    private static boolean accountBanCandidate(Trade trade) {
        return trade.status() == TradeStatus.PENDING_ACCEPTANCE || trade.status().isActive();
    }

    private int closePending(WriteTransaction transaction, List<Trade> trades, Map<Long, Long> branches,
                             CloseReason reason, String basisRef, Instant now) {
        int changed = 0;
        for (var trade : trades) {
            closeRequest(transaction, trade, branches.get(trade.id()), reason, reason.value(), basisRef,
                    Set.of(trade.buyerId()), now);
            changed++;
        }
        return changed;
    }

    private int applyAccountBan(WriteTransaction transaction, long restrictionId, String reason, String basisRef,
                                List<Trade> trades, Map<Long, Long> branches, Instant now) {
        int changed = 0;
        for (var trade : trades) {
            requirePartyFreezeLocks(transaction, trade);
            long branch = branches.get(trade.id());
            var parties = Set.of(trade.buyerId(), trade.sellerId());
            if (trade.status() == TradeStatus.PENDING_ACCEPTANCE) {
                closeRequest(transaction, trade, branch, CloseReason.ACCOUNT_BANNED, reason, basisRef, parties, now);
                changed++;
            } else if (accountFreeze(trade.id(), restrictionId).isEmpty()) {
                repository.insertFreeze(trade.id(), FreezeSource.ACCOUNT_BAN, restrictionId, reason, now);
                pauseWait(transaction, trade.id(), now);
                repository.touch(trade.id(), now);
                UUID event = UUID.randomUUID();
                long historyId = historyWriter.history(transaction,
                        trade, trade, "trade.freeze", ActorKind.SYSTEM, null,
                        reason, basisRef, null, event, now);
                conversations.append(transaction, branch, event, "trade_frozen",
                        "账户受限，交易已冻结", new ResourceRef("trade_transition", historyId));
                notify(transaction, trade, parties, "trade.frozen", event);
                changed++;
            }
        }
        return changed;
    }

    private int removeAccountBan(WriteTransaction transaction, long restrictionId, String basisRef,
                                 List<Trade> trades, Map<Long, Long> branches, Instant now) {
        int changed = 0;
        for (var trade : trades) {
            var freeze = accountFreeze(trade.id(), restrictionId);
            if (freeze.isEmpty()) {
                continue;
            }
            requirePartyFreezeLocks(transaction, trade);
            repository.endFreeze(freeze.orElseThrow().id(), null, now);
            repository.touch(trade.id(), now);
            resumeWaitIfPossible(transaction, trade, now);
            UUID event = UUID.randomUUID();
            long historyId = historyWriter.history(transaction, trade, trade, "trade.unfreeze", ActorKind.SYSTEM, null,
                    null, basisRef, null, event, now);
            conversations.append(transaction, branches.get(trade.id()), event, "trade_unfrozen", "交易冻结已解除",
                    new ResourceRef("trade_transition", historyId));
            notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.unfrozen", event);
            changed++;
        }
        return changed;
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
        return closurePlan(tradeIds, LockPlan.AccountMode.SHARED);
    }

    private LockPlan closurePlan(Collection<Long> tradeIds, LockPlan.AccountMode partyMode) {
        var accounts = new TreeSet<Long>();
        var resources = new TreeSet<LockPlan.Key>();
        for (long id : tradeIds) {
            var trade = repository.find(id).orElseThrow(Trade::notVisible);
            accounts.add(trade.buyerId());
            accounts.add(trade.sellerId());
            resources.add(tradeKey(id));
            conversations.find(id).ifPresent(conversationId -> resources.add(conversationKey(conversationId)));
        }
        var modes = new TreeMap<Long, LockPlan.AccountMode>();
        accounts.forEach(id -> modes.put(id, partyMode));
        return new LockPlan(modes, resources);
    }

    private List<Trade> lockAffected(WriteTransaction transaction, LockPlan plan, Collection<Long> ids) {
        var needed = closurePlan(ids);
        if (!plan.accounts().keySet().containsAll(needed.accounts().keySet())) {
            throw new LockPlan.Changed(needed);
        }
        return ids.stream().sorted().map(id -> repository.lockTrade(transaction, id)).toList();
    }

    /**
     * Reads the candidate rows after their locks were acquired by a caller-owned subject plan. A
     * candidate that grew after the plan was prepared is reported through {@link LockPlan.Changed}
     * so the executor rolls back and re-plans the whole batch.
     */
    private List<Trade> acquiredTrades(WriteTransaction transaction, Collection<Long> ids) {
        var trades = new ArrayList<Trade>();
        for (long id : new TreeSet<>(ids)) {
            var key = tradeKey(id);
            if (!transaction.isAcquired(key)) {
                throw new LockPlan.Changed(new LockPlan(Map.of(), Set.of(key)));
            }
            trades.add(repository.find(id).orElseThrow(Trade::notVisible));
        }
        return trades;
    }

    private Map<Long, Long> acquiredBranches(WriteTransaction transaction, Collection<Trade> trades) {
        var branches = new TreeMap<Long, Long>();
        for (var trade : trades) {
            long branch = requireConversationId(trade.id());
            var key = conversationKey(branch);
            if (!transaction.isAcquired(key)) {
                throw new LockPlan.Changed(new LockPlan(Map.of(), Set.of(key)));
            }
            branches.put(trade.id(), branch);
        }
        return branches;
    }

    private Map<Long, Long> lockBranches(WriteTransaction transaction, Collection<Trade> trades) {
        var branches = new TreeMap<Long, Long>();
        for (var trade : trades) {
            branches.put(trade.id(), requireConversationId(trade.id()));
        }
        for (long branch : new TreeSet<>(branches.values())) {
            conversations.lockConversation(transaction, branch);
        }
        return branches;
    }

    private void closeRequest(WriteTransaction transaction, Trade trade, long branch, CloseReason cause,
                              String reason, String basisRef, Set<Long> recipients, Instant now) {
        var closed = changed(trade, TradeStatus.CLOSED, null, cause.value(), null, now, null, now);
        repository.save(closed);
        UUID event = UUID.randomUUID();
        historyWriter.history(transaction, trade, closed, "request.close", ActorKind.SYSTEM, null, reason,
                basisRef, null, event, now);
        conversations.append(transaction, branch, event, "request_closed", "购买请求已关闭", null);
        archive(transaction, branch, trade.id(), cause.value());
        notify(transaction, trade, recipients, "trade.request_closed", event);
    }

    // ---------------------------------------------------------------- timeout task support

    public LockPlan timeoutPlan(long tradeId) {
        return timeout.timeoutPlan(tradeId);
    }

    public void lockForTimeout(WriteTransaction transaction, long tradeId) {
        timeout.lockForTimeout(transaction, tradeId);
    }

    public boolean timeoutApplicable(long tradeId, String sourceVersion) {
        return timeout.timeoutApplicable(tradeId, sourceVersion);
    }

    public void applyTimeout(WriteTransaction transaction, ExecutionContext context, long tradeId,
                             String sourceVersion) {
        timeout.applyTimeout(transaction, context, tradeId, sourceVersion);
    }

    // ---------------------------------------------------------------- queries and read ports

    /** Projects the agreement and confirmation records for an already authorized case target. */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ObjectNode caseHistory(long tradeId) {
        return queries.caseHistory(tradeId);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode getTrade(ExecutionContext context, long tradeId, List<String> include) {
        return queries.getTrade(context, tradeId, include);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public JsonNode listMine(ExecutionContext context, String role, List<String> statusValues, Integer page,
                             Integer pageSize) {
        return queries.listMine(context, role, statusValues, page, pageSize);
    }

    @Override
    public Optional<TradeModels.ConversationAccess> findConversationAccess(long tradeId) {
        return repository.find(tradeId)
                .map(trade -> new TradeModels.ConversationAccess(trade.buyerId(), trade.sellerId(), trade.status()));
    }

    public record NotificationContext(String productTitle, String requestNote) {}

    public Optional<NotificationContext> notificationContext(long tradeId, long viewerId) {
        return repository.find(tradeId)
                .filter(trade -> trade.isParticipant(viewerId))
                .map(trade -> {
                    String title = repository.snapshot(tradeId).map(element -> element.title())
                            .or(() -> product.visibleSummary(trade.productId(), viewerId)
                                    .map(entry -> entry.title()))
                            .orElse(null);
                    return new NotificationContext(title, trade.requestNote());
                });
    }

    @Override
    public TradeModels.ConversationAccess conversationAccess(long tradeId) {
        return findConversationAccess(tradeId).orElseThrow(Trade::notVisible);
    }

    @Override
    public java.util.OptionalLong productId(long tradeId) {
        return repository.find(tradeId).map(trade -> java.util.OptionalLong.of(trade.productId()))
                .orElseGet(java.util.OptionalLong::empty);
    }

    @Override
    public boolean pairFrozen(long firstAccountId, long secondAccountId) {
        return repository.pairFrozen(firstAccountId, secondAccountId);
    }

    @Override
    public List<Long> tradeIdsOf(long accountId) {
        return repository.tradeIdsForAccount(accountId);
    }

    public TradeModels.ReviewEligibility reviewEligibility(long tradeId, long reviewerId) {
        return reviews.reviewEligibility(tradeId, reviewerId);
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
        return TradeWriteSupport.prepareTrade(repository, conversations, actor, tradeId, product, caseId);
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
        TradeWriteSupport.replayTrade(repository, context, resource);
    }

    private void replayGovernance(ExecutionContext context, Object qualification, ResourceRef resource) {
        actor(context);
    }

    private Map<Long, LockPlan.AccountMode> sharedAccounts(Collection<Long> accountIds) {
        return TradeWriteSupport.sharedAccounts(accountIds);
    }

    private void requireWrite(long accountId) {
        TradeWriteSupport.requireWrite(accounts, accountId);
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
        long historyId = historyWriter.historyFreeze(transaction,
                trade, "trade.freeze", ActorKind.ADMIN, manager, reason,
                basisRef, caseId, freezeId, frozenBefore, true, eventId, now);
        return Optional.of(new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                trade.status().value(), TradeHistoryWriter.phase(trade.phase()),
                TradeHistoryWriter.phase(trade.phase()), frozenBefore, true, false));
    }

    private TradePorts.CaseEnforcementOutcome liftFreezeFacts(WriteTransaction transaction, Trade trade,
                                                              TradeModels.Freeze freeze, long caseId, long manager,
                                                              String basisRef, String reason, Instant now,
                                                              UUID eventId) {
        repository.endFreeze(freeze.id(), manager, now);
        repository.touch(trade.id(), now);
        resumeWaitIfPossible(transaction, trade, now);
        boolean frozenAfter = !repository.activeFreezes(trade.id()).isEmpty();
        long historyId = historyWriter.historyFreeze(transaction,
                trade, "trade.unfreeze", ActorKind.ADMIN, manager, reason,
                basisRef, caseId, freeze.id(), true, frozenAfter, eventId, now);
        return new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                trade.status().value(), TradeHistoryWriter.phase(trade.phase()),
                TradeHistoryWriter.phase(trade.phase()), true, frozenAfter, false);
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
        long historyId = historyWriter.historyAgreement(transaction, trade, ended,
                target == TradeStatus.COMPLETED ? "trade.completed" : "trade.terminated", ActorKind.ADMIN,
                manager, reason, basisRef, caseId, trade.activeAgreementId(), null, eventId, now);
        return new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                target.value(), TradeHistoryWriter.phase(trade.phase()),
                TradeHistoryWriter.phase(ended.phase()), frozenBefore, false, false);
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
        long historyId = historyWriter.historyAgreement(transaction, trade, restored, "trade.restore", ActorKind.ADMIN,
                manager, reason, basisRef, caseId, trade.activeAgreementId(), null, eventId, now);
        return new TradePorts.CaseEnforcementOutcome(trade.id(), historyId, eventId, trade.status().value(),
                TradeStatus.IN_PROGRESS.value(), TradeHistoryWriter.phase(trade.phase()),
                TradeHistoryWriter.phase(restored.phase()), frozen, frozen,
                false);
    }

    /**
     * Ordinary case lifts carry no freeze id. Resolve only the one active freeze whose provenance
     * is this case: an admin-case freeze or a system timeout freeze recorded with this case as
     * {@code source_ref}. Account bans and case freezes owned by another case are never candidates;
     * zero or multiple matching rows fail closed.
     */
    private TradeModels.Freeze caseSourcedFreeze(Trade trade, long caseId) {
        var matches = repository.activeFreezes(trade.id()).stream()
                .filter(freeze -> freeze.tradeId() == trade.id())
                .filter(freeze -> freeze.source() == FreezeSource.ADMIN_CASE
                        || freeze.source() == FreezeSource.TIMEOUT)
                .filter(freeze -> Objects.equals(freeze.sourceRef(), caseId))
                .toList();
        if (matches.size() > 1) {
            throw new BusinessError("TRADE_FREEZE_NOT_ACTIVE", 409, "交易冻结来源无法唯一定位");
        }
        if (matches.isEmpty()) {
            throw freezeNotActive();
        }
        return matches.getFirst();
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
        return TradeWriteSupport.lockProduct(product, transaction, productId);
    }

    private void lockCase(WriteTransaction transaction, long caseId, long manager, long tradeId, String basisRef) {
        transaction.lock(caseKey(caseId), () -> cases.lockAndValidate(transaction, caseId, manager, tradeId, basisRef));
    }

    private long requireConversation(WriteTransaction transaction, long tradeId) {
        return TradeWriteSupport.requireConversation(transaction, conversations, queries, tradeId);
    }

    private long requireConversationId(long tradeId) {
        return queries.requireConversationId(tradeId);
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
        TradeWriteSupport.endWait(repository, tradeId, reason, now);
    }

    private void endFreezes(WriteTransaction transaction, long tradeId, Instant now) {
        repository.endAllFreezes(tradeId, now);
    }

    private void scheduleTimeout(long tradeId, TradeModels.Wait wait, Instant now) {
        TradeWriteSupport.scheduleTimeout(schedules, tradeId, wait, now);
    }

    private Trade changed(Trade trade, TradeStatus status, Long activeAgreementId, String closeReason,
                          String terminalReason, Instant respondedAt, Instant endedAt, Instant now) {
        return TradeWriteSupport.changed(trade, status, activeAgreementId, closeReason, terminalReason,
                respondedAt, endedAt, now);
    }

    private void publishFreeze(WriteTransaction transaction, Trade trade, long conversationId, long caseId,
                               UUID eventId, TradePorts.CaseEnforcementOutcome outcome) {
        conversations.append(transaction, conversationId, eventId, "trade_frozen",
                "交易已被冻结", outcome.transitionRef());
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.frozen", eventId);
        audit(transaction, "trade.freeze", trade.id(), new ResourceRef("case", caseId));
    }

    private void publishLift(WriteTransaction transaction, Trade trade, long conversationId, long caseId,
                             UUID eventId, TradePorts.CaseEnforcementOutcome outcome) {
        conversations.append(transaction, conversationId, eventId, "trade_unfrozen", "交易冻结已解除",
                outcome.transitionRef());
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.unfrozen", eventId);
        audit(transaction, "trade.freeze.lift", trade.id(), new ResourceRef("case", caseId));
    }

    private void publishAdjust(WriteTransaction transaction, Trade trade, long conversationId, long caseId,
                               UUID eventId, TradeStatus target, ResourceRef transitionRef) {
        conversations.append(transaction, conversationId, eventId,
                target == TradeStatus.COMPLETED ? "trade_completed" : "trade_terminated",
                "管理员调整交易状态，如需继续出售，可前往商品详情重新上架。", transitionRef);
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.adjusted", eventId);
        archive(transaction, conversationId, trade.id(), "admin_" + target.value());
        audit(transaction, "trade.adjust", trade.id(), new ResourceRef("case", caseId));
    }

    private void publishRestore(WriteTransaction transaction, Trade trade, long conversationId, long caseId,
                                UUID eventId, TradePorts.CaseEnforcementOutcome outcome) {
        conversations.append(transaction, conversationId, eventId, "trade_restored",
                "异常交易已恢复进行", outcome.transitionRef());
        notify(transaction, trade, Set.of(trade.buyerId(), trade.sellerId()), "trade.restored", eventId);
        audit(transaction, "trade.restore", trade.id(), new ResourceRef("case", caseId));
    }

    private void notify(WriteTransaction transaction, Trade trade, Set<Long> recipients, String eventType,
                        UUID businessEventId) {
        // S1 event types are underscore identifiers; business vocabulary uses dotted names elsewhere.
        notifications.register(transaction, businessEventId, eventType, trade.id(), recipients);
    }

    private void audit(WriteTransaction transaction, String action, long tradeId,
                       ResourceRef basis) {
        TradeWriteSupport.audit(json, transaction, action, tradeId, basis);
    }

    private ObjectNode view(long tradeId, long viewer, Long knownConversationId) {
        return queries.view(tradeId, viewer, knownConversationId);
    }

    private ObjectNode agreementEnvelope(TradeModels.Agreement agreement, long tradeId, long viewer) {
        var node = json.createObjectNode();
        node.set("agreement", views.agreementItem(agreement));
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

    private static TradeModels.Agreement withId(TradeModels.Agreement agreement, long id) {
        return new TradeModels.Agreement(id, agreement.tradeId(), agreement.baseAgreementId(), agreement.versionNo(),
                agreement.status(), agreement.proposedBy(), agreement.deliveryAt(), agreement.deliveryPlaceText(),
                agreement.deliveryMethod(), agreement.amountCents(), agreement.paymentMethod(),
                agreement.paymentTiming(), agreement.proposedAt(), agreement.businessEventId());
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

    private void requireNotFrozen(WriteTransaction transaction, long tradeId) {
        TradeWriteSupport.requireNotFrozen(repository, tradeId);
    }

    /**
     * Rejects a new trade when either role is still covered by an unended trade freeze. This is
     * deliberately separate from {@link #requireNotFrozen}: a trade that does not exist yet has no
     * freeze row of its own, so the fact belongs to the account's existing frozen trades.
     */
    private void requireNoActivePartyFreeze(long accountId) {
        if (repository.hasActivePartyFreeze(accountId)) {
            throw new BusinessError("TRADE_FROZEN", 409, "交易冻结期间不能发起新交易");
        }
    }

    /**
     * Freeze and unfreeze are qualification changes for both parties, so their authors must hold
     * the exclusive account lock before they read or write the freeze fact. The write executor
     * replans with the stronger mode if a caller still prepared a shared lock.
     */
    private static void requirePartyFreezeLocks(WriteTransaction transaction, Trade trade) {
        TradeWriteSupport.requirePartyFreezeLocks(transaction, trade);
    }

    private long actor(ExecutionContext context) {
        return TradeWriteSupport.actor(context);
    }

    private long other(Trade trade, long accountId) {
        return TradeWriteSupport.other(trade, accountId);
    }

    private static Decision decision(String value) {
        return TradeWriteSupport.decision(value);
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
        return TradeWriteSupport.now(clock, repository);
    }

    private static BusinessError inputInvalid(String message) {
        return TradeWriteSupport.inputInvalid(message);
    }

    private static BusinessError versionConflict() {
        return new BusinessError("VERSION_CONFLICT", 409, "版本已变化");
    }

    private static BusinessError productUnavailable() {
        return TradeWriteSupport.productUnavailable();
    }

    private static String requiredText(String value, int max, String field) {
        return TradeWriteSupport.requiredText(value, max, field);
    }

    private static String optionalText(String value, int max, String field) {
        return TradeWriteSupport.optionalText(value, max, field);
    }

    private static LockPlan.Key productKey(long productId) {
        return TradeWriteSupport.productKey(productId);
    }

    private static LockPlan.Key tradeKey(long tradeId) {
        return TradeWriteSupport.tradeKey(tradeId);
    }

    private static LockPlan.Key caseKey(long caseId) {
        return TradeWriteSupport.caseKey(caseId);
    }

    private static LockPlan.Key conversationKey(long conversationId) {
        return TradeWriteSupport.conversationKey(conversationId);
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
