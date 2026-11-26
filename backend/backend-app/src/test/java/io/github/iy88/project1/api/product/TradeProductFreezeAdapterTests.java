package io.github.iy88.project1.api.product;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.trade.application.TradePorts;
import org.junit.jupiter.api.Test;

class TradeProductFreezeAdapterTests {
    @Test
    void delegatesThePartyFreezeReadToTheTradeClosurePort() {
        var closures = mock(TradePorts.Closure.class);
        when(closures.hasActivePartyFreeze(7L)).thenReturn(true);

        assertThat(new TradeProductFreezeAdapter(closures).isPartyFrozen(7L)).isTrue();

        verify(closures).hasActivePartyFreeze(7L);
    }
}
