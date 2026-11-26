package io.github.iy88.project1.api.trade;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductTradeStore;
import io.github.iy88.project1.trade.application.TradePorts;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class TradeProductAdapterTests {
    private final ProductTradeStore store = mock(ProductTradeStore.class);
    private final TradeProductAdapter adapter = new TradeProductAdapter(store);

    @Test
    void publicProductIsTradableForOtherAccounts() {
        adapter.requireTradable(state("public", null, 9), 1);
    }

    @Test
    void selfPurchaseAndNonPublicStatesAreRejected() {
        assertThatThrownBy(() -> adapter.requireTradable(state("public", null, 1), 1))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("PRODUCT_NOT_AVAILABLE"));
        assertThatThrownBy(() -> adapter.requireTradable(state("in_trade", 77L, 9), 1))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("PRODUCT_NOT_AVAILABLE"));
        assertThatThrownBy(() -> adapter.requireTradable(state("off_shelf", null, 9), 1))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("PRODUCT_NOT_AVAILABLE"));
    }

    @Test
    void occupancyOwnedByAnotherTradeConflicts() {
        adapter.requireNoOccupancy(state("public", 77L, 9), 77);
        adapter.requireNoOccupancy(state("public", null, 9), 77);
        assertThatThrownBy(() -> adapter.requireNoOccupancy(state("public", 78L, 9), 77))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("OCCUPANCY_CONFLICT"));
    }

    @Test
    void summaryIsVisibleToThePublicAndToTheSellerOnly() {
        when(store.read(5)).thenReturn(Optional.of(product("public")));
        assertThat(adapter.visibleSummary(5, 3)).isPresent();
        assertThat(adapter.visibleSummary(5, 9)).contains(new TradePorts.ProductSummary("标题", 1200));

        when(store.read(5)).thenReturn(Optional.of(product("off_shelf")));
        assertThat(adapter.visibleSummary(5, 3)).isEmpty();
        assertThat(adapter.visibleSummary(5, 9)).isPresent();
    }

    private static ProductTradeStore.TradeProduct product(String lifecycle) {
        return new ProductTradeStore.TradeProduct(5, 9, 3, lifecycle, null, "标题", "描述", 1200,
                List.of("书籍"), List.of(11L));
    }

    private static TradePorts.ProductState state(String lifecycle, Long occupancy, long sellerId) {
        return new TradePorts.ProductState(5, sellerId, 3, lifecycle, occupancy, "标题", "描述", 1200,
                List.of(), List.of());
    }
}
