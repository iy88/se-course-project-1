package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Trade detail reads, their shared projection and the account/case history queries.
 *
 * <p>The public entry points and their Spring transaction annotations stay on the application
 * entry class; writes call {@link #view} inside their own transaction so they return the same
 * projection as the detail reads.
 */
final class TradeQueries {
    private final TradeRepository repository;
    private final TradeViews views;
    private final TradePorts.Accounts accounts;
    private final TradePorts.Product product;
    private final TradePorts.Conversation conversations;
    private final TradeSettings settings;
    private final JsonMapper json;
    private final Clock clock;

    TradeQueries(TradeRepository repository, TradeViews views, TradePorts.Accounts accounts,
                 TradePorts.Product product, TradePorts.Conversation conversations,
                 TradeSettings settings, JsonMapper json, Clock clock) {
        this.repository = repository;
        this.views = views;
        this.accounts = accounts;
        this.product = product;
        this.conversations = conversations;
        this.settings = settings;
        this.json = json;
        this.clock = clock;
    }

    ObjectNode caseHistory(long tradeId) {
        repository.find(tradeId).orElseThrow(Trade::notVisible);
        var node = json.createObjectNode().put("trade_id", Long.toString(tradeId));
        views.agreements(node, limit(repository.agreements(tradeId)));
        views.confirmations(node, limit(repository.confirmations(tradeId)));
        return node;
    }

    JsonNode getTrade(ExecutionContext context, long tradeId, List<String> include) {
        long viewer = TradeWriteSupport.actor(context);
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        trade.requireParticipant(viewer);
        var allowed = Set.of("agreement_history", "confirmation_history", "state_history");
        for (String value : include) {
            if (!allowed.contains(value)) {
                throw TradeWriteSupport.inputInvalid("include 参数无效");
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

    JsonNode listMine(ExecutionContext context, String role, List<String> statusValues, Integer page,
                      Integer pageSize) {
        long viewer = TradeWriteSupport.actor(context);
        String normalizedRole = role == null || role.isBlank() ? "all" : role;
        if (!Set.of("all", "buyer", "seller").contains(normalizedRole)) {
            throw TradeWriteSupport.inputInvalid("role 参数无效");
        }
        int size = pageSize == null ? settings.pageSizeDefault() : pageSize;
        int number = page == null ? 1 : page;
        if (number < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw TradeWriteSupport.inputInvalid("分页参数无效");
        }
        var statuses = new ArrayList<TradeStatus>();
        for (String value : statusValues) {
            try {
                statuses.add(TradeStatus.from(value));
            } catch (IllegalArgumentException invalid) {
                throw TradeWriteSupport.inputInvalid("status 参数无效");
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

    ObjectNode view(long tradeId, long viewer, Long knownConversationId) {
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
                qualification.exists() && !qualification.writeRestricted(),
                TradeWriteSupport.now(clock, repository));
    }

    long requireConversationId(long tradeId) {
        return conversations.find(tradeId).orElseThrow(() -> new BusinessError(
                "TRADE_CONVERSATION_NOT_FOUND", 409, "交易会话不存在"));
    }

    private <T> List<T> limit(List<T> values) {
        return values.size() <= settings.historyLimit() ? values : values.subList(0, settings.historyLimit());
    }
}
