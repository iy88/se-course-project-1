package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Completed-trade review use cases and their read projections, owned by the trade module. */
final class TradeReviews implements WriteExecutor.UseCase<TradeCommands.SubmitReview, Object> {
    private final TradeRepository repository;
    private final TradeViews views;
    private final TradePorts.Accounts accounts;
    private final TradeSettings settings;
    private final JsonMapper json;
    private final Clock clock;

    TradeReviews(TradeRepository repository, TradeViews views, TradePorts.Accounts accounts, TradeSettings settings,
                 JsonMapper json, Clock clock) {
        this.repository = repository;
        this.views = views;
        this.accounts = accounts;
        this.settings = settings;
        this.json = json;
        this.clock = clock;
    }

    @Override
    public JsonNode digestInput(TradeCommands.SubmitReview request) {
        return json.valueToTree(request);
    }

    @Override
    public LockPlan prepare(ExecutionContext context, TradeCommands.SubmitReview request) {
        return prepareReview(TradeWriteSupport.actor(context), request.tradeId());
    }

    @Override
    public Object qualify(ExecutionContext context, TradeCommands.SubmitReview request, LockPlan plan) {
        return qualifyReview(context, request.tradeId());
    }

    @Override
    public void requireReplayAccess(ExecutionContext context, Object qualification, ResourceRef resource) {
        TradeWriteSupport.replayTrade(repository, context, resource);
    }

    @Override
    public WriteResult.Response<?> write(WriteTransaction transaction, TradeCommands.SubmitReview request,
                                         Object qualification, LockPlan plan) {
        long reviewer = TradeWriteSupport.actor(transaction.context());
        int rating = rating(request.rating());
        String content = requiredTrimmedText(request.content(), 2000, "评价内容");
        var trade = repository.lockTrade(transaction, request.tradeId());
        requireReviewParticipant(trade, reviewer);
        TradeWriteSupport.requireWrite(accounts, reviewer);
        if (trade.status() != TradeStatus.COMPLETED) {
            throw reviewNotCompleted();
        }
        if (repository.review(trade.id(), reviewer).isPresent()) {
            throw reviewAlreadySubmitted();
        }
        long reviewee = TradeWriteSupport.other(trade, reviewer);
        var now = TradeWriteSupport.now(clock, repository);
        var review = new TradeModels.Review(0, trade.id(), reviewer, reviewee, rating, content, true, now);
        review = withReviewId(review, repository.insertReview(review));
        var profiles = accounts.profiles(Set.of(reviewer, reviewee));
        var body = json.createObjectNode();
        body.set("review", views.reviewView(review, profiles));
        TradeWriteSupport.audit(json, transaction, "trade.review.submit", trade.id(),
                new ResourceRef("trade_review", review.id()));
        return new WriteResult.Response<>(201, body, new ResourceRef("trade", trade.id()));
    }

    JsonNode getTradeReviews(ExecutionContext context, long tradeId) {
        long viewer = TradeWriteSupport.actor(context);
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        trade.requireParticipant(viewer);
        long counterpart = TradeWriteSupport.other(trade, viewer);
        var written = repository.review(tradeId, viewer).orElse(null);
        var received = repository.review(tradeId, counterpart).orElse(null);
        var profiles = accounts.profiles(Set.of(trade.buyerId(), trade.sellerId()));
        var qualification = accounts.qualification(viewer);
        var node = json.createObjectNode();
        node.put("can_review", canReview(trade, written, qualification));
        node.set("written", written == null ? json.nullNode() : views.reviewView(written, profiles));
        node.set("received", received == null ? json.nullNode() : views.reviewView(received, profiles));
        return node;
    }

    JsonNode listMyReviews(ExecutionContext context, String direction, Integer page, Integer pageSize) {
        long viewer = TradeWriteSupport.actor(context);
        String normalized = direction == null || direction.isBlank() ? "written" : direction;
        if (!Set.of("written", "received").contains(normalized)) {
            throw TradeWriteSupport.inputInvalid("direction 参数无效");
        }
        int size = pageSize == null ? settings.pageSizeDefault() : pageSize;
        int number = page == null ? 1 : page;
        if (number < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw TradeWriteSupport.inputInvalid("分页参数无效");
        }
        var result = repository.pageReviews(viewer, normalized, size, (number - 1L) * size);
        var accountIds = new TreeSet<Long>();
        for (var review : result.reviews()) {
            accountIds.add(review.reviewerId());
            accountIds.add(review.revieweeId());
        }
        var profiles = accounts.profiles(accountIds);
        var node = json.createObjectNode();
        var items = node.putArray("items");
        result.reviews().forEach(review -> items.add(views.reviewView(review, profiles)));
        node.put("page", number);
        node.put("page_size", size);
        node.put("total", result.total());
        return node;
    }

    TradeModels.ReviewEligibility reviewEligibility(long tradeId, long reviewerId) {
        var found = repository.find(tradeId);
        if (found.isEmpty()) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, 0, false, "trade_not_found");
        }
        var trade = found.orElseThrow();
        if (!trade.isParticipant(reviewerId)) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, 0, false, "not_participant");
        }
        long reviewee = TradeWriteSupport.other(trade, reviewerId);
        if (trade.status() != TradeStatus.COMPLETED) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, reviewee, false, "trade_not_completed");
        }
        var written = repository.review(tradeId, reviewerId).orElse(null);
        if (written != null) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, reviewee, false, "already_reviewed");
        }
        var qualification = accounts.qualification(reviewerId);
        if (!canReview(trade, written, qualification)) {
            return new TradeModels.ReviewEligibility(tradeId, reviewerId, reviewee, false,
                    "account_write_restricted");
        }
        return new TradeModels.ReviewEligibility(tradeId, reviewerId, reviewee, true, "eligible");
    }

    private static boolean canReview(Trade trade, TradeModels.Review written,
                                     TradePorts.AccountQualification qualification) {
        return trade.status() == TradeStatus.COMPLETED && written == null
                && qualification.exists() && !qualification.writeRestricted();
    }

    private LockPlan prepareReview(long reviewer, long tradeId) {
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        var accountsSet = new TreeSet<Long>(List.of(reviewer, trade.buyerId(), trade.sellerId()));
        return new LockPlan(TradeWriteSupport.sharedAccounts(accountsSet),
                Set.of(TradeWriteSupport.tradeKey(tradeId)));
    }

    private Void qualifyReview(ExecutionContext context, long tradeId) {
        accounts.requireCurrentSession(context);
        var trade = repository.find(tradeId).orElseThrow(Trade::notVisible);
        requireReviewParticipant(trade, TradeWriteSupport.actor(context));
        return null;
    }

    private static void requireReviewParticipant(Trade trade, long reviewer) {
        if (!trade.isParticipant(reviewer)) {
            throw Trade.actionNotAllowed();
        }
    }

    private static BusinessError reviewNotCompleted() {
        return new BusinessError("TRADE_NOT_COMPLETED", 409, "交易完成后才能评价");
    }

    private static BusinessError reviewAlreadySubmitted() {
        return new BusinessError("REVIEW_ALREADY_SUBMITTED", 409, "本人已评价本笔交易");
    }

    private static int rating(Integer value) {
        if (value == null || value < 1 || value > 5) {
            throw TradeWriteSupport.inputInvalid("评分须为1到5的整数");
        }
        return value;
    }

    private static String requiredTrimmedText(String value, int max, String field) {
        if (value == null || value.isBlank()) {
            throw TradeWriteSupport.inputInvalid(field + "不能为空");
        }
        String trimmed = value.trim();
        if (trimmed.length() > max) {
            throw TradeWriteSupport.inputInvalid(field + "长度不能超过" + max);
        }
        return trimmed;
    }

    private static TradeModels.Review withReviewId(TradeModels.Review review, long id) {
        return new TradeModels.Review(id, review.tradeId(), review.reviewerId(), review.revieweeId(),
                review.rating(), review.content(), review.visible(), review.createdAt());
    }
}
