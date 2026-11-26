package io.github.iy88.project1.api.product;

import io.github.iy88.project1.product.application.ProductTradeFreeze;
import io.github.iy88.project1.trade.application.TradePorts;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Binds the product-side party-freeze port to the trade-owned closure projection. */
@Component
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeProductFreezeAdapter implements ProductTradeFreeze {
    private final TradePorts.Closure closures;

    TradeProductFreezeAdapter(TradePorts.Closure closures) {
        this.closures = closures;
    }

    @Override
    public boolean isPartyFrozen(long accountId) {
        return closures.hasActivePartyFreeze(accountId);
    }
}
