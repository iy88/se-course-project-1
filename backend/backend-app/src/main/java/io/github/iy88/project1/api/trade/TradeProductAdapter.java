package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductTradeStore;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradePorts.ProductState;
import io.github.iy88.project1.trade.application.TradePorts.ProductSummary;
import java.time.Instant;
import java.util.Optional;

/** Product-owned implementation of the trade product port. */
final class TradeProductAdapter implements TradePorts.Product {
    private final ProductTradeStore products;

    TradeProductAdapter(ProductTradeStore products) {
        this.products = products;
    }

    @Override
    public Optional<ProductState> read(long productId) {
        return products.read(productId).map(TradeProductAdapter::state);
    }

    @Override
    public Optional<ProductSummary> visibleSummary(long productId, long viewerId) {
        return products.read(productId)
                .filter(product -> product.sellerId() == viewerId
                        || Product.PUBLIC.equals(product.lifecycleState()) && !products.displayRestricted(productId))
                .map(product -> new ProductSummary(product.title(), product.priceCents()));
    }

    @Override
    public ProductState lock(WriteTransaction transaction, long productId) {
        return products.lock(productId).map(TradeProductAdapter::state).orElse(null);
    }

    @Override
    public void requireTradable(ProductState state, long buyerId) {
        if (!Product.PUBLIC.equals(state.lifecycleState()) || state.sellerId() == buyerId
                || products.displayRestricted(state.productId())) {
            throw new BusinessError("PRODUCT_NOT_AVAILABLE", 409, "商品当前不可交易");
        }
    }

    @Override
    public void requireNoOccupancy(ProductState state, long tradeId) {
        Long holder = state.occupancyTradeId();
        if (holder != null && holder != tradeId) {
            throw new BusinessError("OCCUPANCY_CONFLICT", 409, "商品已被其他交易占用");
        }
    }

    @Override
    public void acquire(WriteTransaction transaction, ProductState state, long tradeId) {
        products.acquire(state.productId(), tradeId, Instant.now());
    }

    @Override
    public void release(WriteTransaction transaction, ProductState state, long tradeId, String reason) {
        products.release(state.productId(), tradeId, Instant.now());
    }

    @Override
    public void releaseToPublic(WriteTransaction transaction, ProductState state, long tradeId, String reason) {
        products.releaseToPublic(state.productId(), tradeId, Instant.now());
    }

    private static ProductState state(ProductTradeStore.TradeProduct product) {
        return new ProductState(product.productId(), product.sellerId(), product.contentVersion(),
                product.lifecycleState(), product.occupiedByTradeId(), product.title(),
                product.description(), product.priceCents(), product.categoryNames(),
                product.imageFileIds());
    }
}
