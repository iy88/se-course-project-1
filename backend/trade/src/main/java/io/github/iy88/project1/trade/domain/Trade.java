package io.github.iy88.project1.trade.domain;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Trade aggregate root. All derived state and action eligibility live here. */
public record Trade(long id, long productId, long buyerId, long sellerId, TradeStatus status, String requestNote,
                    Long activeAgreementId, int version, String closeReason, String terminalReason,
                    Instant requestedAt, Instant respondedAt, Instant endedAt, Instant createdAt, Instant updatedAt) {

    public TradePhase phase() {
        if (!status.isActive()) {
            return null;
        }
        return activeAgreementId == null ? TradePhase.FIRST_AGREEMENT_PENDING : TradePhase.AWAITING_COMPLETION;
    }

    public boolean isParticipant(long accountId) {
        return buyerId == accountId || sellerId == accountId;
    }

    public TradeVocabulary.ActorKind actorKind(long accountId) {
        if (buyerId == accountId) {
            return TradeVocabulary.ActorKind.BUYER;
        }
        if (sellerId == accountId) {
            return TradeVocabulary.ActorKind.SELLER;
        }
        throw notVisible();
    }

    public void requireParticipant(long accountId) {
        if (!isParticipant(accountId)) {
            throw notVisible();
        }
    }

    public void requireBuyer(long accountId) {
        if (buyerId != accountId) {
            throw actionNotAllowed();
        }
    }

    public void requireSeller(long accountId) {
        if (sellerId != accountId) {
            throw actionNotAllowed();
        }
    }

    public void requireNotTerminal() {
        if (status.isTerminal()) {
            throw new BusinessError("TRADE_TERMINAL", 409, "交易已结束");
        }
    }

    public void requireVersion(int expectedVersion) {
        if (version != expectedVersion) {
            throw new BusinessError("VERSION_CONFLICT", 409, "交易版本已变化");
        }
    }

    public void requireStatus(TradeStatus expected) {
        if (status != expected) {
            if (status.isTerminal()) {
                throw new BusinessError("TRADE_TERMINAL", 409, "交易已结束");
            }
            if (status.isEndedRequest()) {
                throw new BusinessError("REQUEST_ALREADY_ENDED", 409, "请求已结束");
            }
            throw stateConflict();
        }
    }

    public void requireInProgress() {
        if (status == TradeStatus.DISPUTED) {
            throw new BusinessError("STATE_CONFLICT", 409, "交易有争议，暂不能执行该操作");
        }
        if (status != TradeStatus.IN_PROGRESS) {
            requireStatus(TradeStatus.IN_PROGRESS);
        }
    }

    public void requireNotDisputed() {
        if (status == TradeStatus.DISPUTED) {
            throw new BusinessError("STATE_CONFLICT", 409, "交易有争议，暂不能执行该操作");
        }
        if (status == TradeStatus.ABNORMAL) {
            throw new BusinessError("STATE_CONFLICT", 409, "异常交易需管理员处理");
        }
    }

    /** First-agreement buyer may cancel directly; every other case needs counterpart approval. */
    public TradeVocabulary.CancellationMode cancellationMode(long actorId, boolean hasCurrentConfirmation) {
        if (status == TradeStatus.IN_PROGRESS && activeAgreementId == null && !hasCurrentConfirmation
                && buyerId == actorId) {
            return TradeVocabulary.CancellationMode.DIRECT;
        }
        return TradeVocabulary.CancellationMode.APPROVAL;
    }

    public void requireNotFrozen(boolean frozen) {
        if (frozen) {
            throw new BusinessError("TRADE_FROZEN", 409, "交易已冻结");
        }
    }

    public List<String> allowedActions(long actorId, boolean pendingAgreement, boolean pendingCancellation,
                                       boolean ownConfirmation, boolean frozen) {
        if (!isParticipant(actorId) || frozen) {
            return List.of();
        }
        var actions = new ArrayList<String>();
        switch (status) {
            case PENDING_ACCEPTANCE -> {
                if (sellerId == actorId) {
                    actions.add("accept");
                    actions.add("reject");
                } else {
                    actions.add("withdraw");
                }
            }
            case IN_PROGRESS -> {
                if (!pendingAgreement) {
                    actions.add("propose_agreement");
                }
                if (activeAgreementId != null && !ownConfirmation) {
                    actions.add("submit_confirmation");
                }
                actions.add("open_dispute");
                if (!pendingCancellation) {
                    actions.add("propose_cancellation");
                }
                if (pendingAgreement) {
                    actions.add("decide_agreement");
                }
                if (pendingCancellation) {
                    actions.add("decide_cancellation");
                }
            }
            case DISPUTED -> {
                if (!pendingCancellation) {
                    actions.add("propose_cancellation");
                }
                actions.add("confirm_dispute_resolution");
                if (pendingCancellation) {
                    actions.add("decide_cancellation");
                }
            }
            case ABNORMAL, COMPLETED, TERMINATED, REJECTED, WITHDRAWN, CLOSED -> {
            }
        }
        return actions;
    }

    public static BusinessError notVisible() {
        return new BusinessError("RESOURCE_NOT_VISIBLE", 404, "交易不存在");
    }

    public static BusinessError actionNotAllowed() {
        return new BusinessError("ACTION_NOT_ALLOWED", 403, "当前身份不能执行该操作");
    }

    public static BusinessError stateConflict() {
        return new BusinessError("STATE_CONFLICT", 409, "交易状态已变化");
    }
}
