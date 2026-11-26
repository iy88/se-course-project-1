package io.github.iy88.project1.trade.domain;

import io.github.iy88.project1.core.BusinessError;
import java.util.Locale;

public enum TradeStatus {
    PENDING_ACCEPTANCE, REJECTED, WITHDRAWN, CLOSED, IN_PROGRESS, DISPUTED, ABNORMAL, TERMINATED, COMPLETED;

    public String value() {
        return name().toLowerCase(Locale.ROOT);
    }

    public static TradeStatus from(String value) {
        return valueOf(value.toUpperCase(Locale.ROOT));
    }

    public boolean isTerminal() {
        return this == COMPLETED || this == TERMINATED;
    }

    public boolean isEndedRequest() {
        return this == REJECTED || this == WITHDRAWN || this == CLOSED;
    }

    public boolean isActive() {
        return this == IN_PROGRESS || this == DISPUTED || this == ABNORMAL;
    }

    public boolean holdsOccupancy() {
        return isActive();
    }

    public void requireTransition(TradeStatus target) {
        if (this.isTerminal()) {
            throw new BusinessError("TRADE_TERMINAL", 409, "交易已结束");
        }
        if (isEndedRequest()) {
            throw new BusinessError("REQUEST_ALREADY_ENDED", 409, "请求已结束");
        }
        boolean allowed = switch (this) {
            case PENDING_ACCEPTANCE -> target == IN_PROGRESS || target == REJECTED
                    || target == WITHDRAWN || target == CLOSED;
            case IN_PROGRESS -> target == DISPUTED || target == ABNORMAL
                    || target == COMPLETED || target == TERMINATED;
            case DISPUTED, ABNORMAL -> target == IN_PROGRESS
                    || target == COMPLETED || target == TERMINATED;
            case COMPLETED, TERMINATED, REJECTED, WITHDRAWN, CLOSED -> false;
        };
        if (!allowed) {
            throw new BusinessError("STATE_CONFLICT", 409, "交易状态已变化");
        }
    }
}
