package io.github.iy88.project1.trade.domain;

import java.util.Locale;

/** Phase is derived from the trade status and the effective agreement, never stored on the trade. */
public enum TradePhase {
    FIRST_AGREEMENT_PENDING, AWAITING_COMPLETION;

    public String value() {
        return name().toLowerCase(Locale.ROOT);
    }

    public static TradePhase from(String value) {
        return valueOf(value.toUpperCase(Locale.ROOT));
    }
}
