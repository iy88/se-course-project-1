package io.github.iy88.project1.api.product;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductService;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import java.util.Map;
import java.util.Set;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Seller off-shelf write owned by the product API boundary.
 *
 * <p>One {@link WriteExecutor} run owns the product lock, every pending trade lock, the trade
 * conversation locks and the product/trade/notification/audit writes. The idempotency filter skips
 * this named route so the shared transaction is the only writer of the operation and audit rows.
 */
@Component
@Profile("infrastructure")
class ProductOffShelfWrite {
    private static final String OPERATION = "product.off_shelf";

    private final WriteExecutor writes;
    private final ProductService products;
    private final ObjectProvider<TradePorts.Closure> closures;
    private final JsonMapper json;

    ProductOffShelfWrite(WriteExecutor writes, ProductService products,
                         ObjectProvider<TradePorts.Closure> closures, JsonMapper json) {
        this.writes = writes;
        this.products = products;
        this.closures = closures;
        this.json = json;
    }

    WriteResult<JsonNode> offShelf(ExecutionContext context, String key, long productId,
                                   Integer expectedVersion) {
        TradePorts.Closure closure = closures.getIfAvailable();
        if (closure == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "交易模块暂不可用");
        }
        return writes.run(context, OPERATION, key, new OffShelfRequest(productId, expectedVersion),
                new OffShelfUseCase(products, closure, json));
    }

    record OffShelfRequest(long productId, Integer expectedVersion) {
    }

    private static final class OffShelfUseCase
            implements WriteExecutor.UseCase<OffShelfRequest, OffShelfRequest> {
        private final ProductService products;
        private final TradePorts.Closure closures;
        private final JsonMapper json;

        private OffShelfUseCase(ProductService products, TradePorts.Closure closures, JsonMapper json) {
            this.products = products;
            this.closures = closures;
            this.json = json;
        }

        @Override
        public JsonNode digestInput(OffShelfRequest request) {
            var node = json.createObjectNode();
            node.put("product_id", Long.toString(request.productId()));
            if (request.expectedVersion() == null) {
                node.putNull("expected_version");
            } else {
                node.put("expected_version", request.expectedVersion());
            }
            return node;
        }

        @Override
        public LockPlan prepare(ExecutionContext context, OffShelfRequest request) {
            return planned(request.productId());
        }

        /**
         * Re-reads the real pending trade candidates under the caller's account advisory locks.
         * A newly created request changes the resource or buyer set, so the whole write restarts
         * with the larger plan instead of closing a partial set or returning a guessed count.
         */
        @Override
        public OffShelfRequest qualify(ExecutionContext context, OffShelfRequest request, LockPlan plan) {
            LockPlan actual = planned(request.productId());
            if (!plan.accounts().keySet().containsAll(actual.accounts().keySet())
                    || !plan.resources().containsAll(actual.resources())) {
                throw new LockPlan.Changed(actual);
            }
            return request;
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, OffShelfRequest request, ResourceRef resource) {
            long sellerId = Long.parseLong(context.actorId());
            if (resource == null || !"product".equals(resource.type())
                    || resource.id() != request.productId()
                    || !products.ownsProduct(sellerId, request.productId())) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
            }
        }

        @Override
        public WriteResult.Response<?> write(WriteTransaction transaction, OffShelfRequest request,
                                             OffShelfRequest qualification, LockPlan plan) {
            long sellerId = Long.parseLong(transaction.context().actorId());
            LockPlan.Key productLock = ProductService.offShelfLockKey(request.productId());
            transaction.lock(productLock,
                    () -> products.lockForOffShelf(sellerId, request.productId(), request.expectedVersion()));
            int closed = closures.closePendingForProduct(transaction, plan, request.productId(),
                    TradeVocabulary.CloseReason.PRODUCT_DELISTED, "product:" + request.productId());
            var result = products.completeOffShelf(sellerId, request.productId(), request.expectedVersion(),
                    closed);
            var facts = json.createObjectNode();
            facts.put("product_id", Long.toString(request.productId()));
            facts.put("closed_pending_request_count", closed);
            transaction.audit(OPERATION, new ResourceRef("product", request.productId()), null, facts);
            return new WriteResult.Response<>(200, result, new ResourceRef("product", request.productId()));
        }

        private LockPlan planned(long productId) {
            LockPlan trades = closures.productClosurePlan(productId);
            return trades.merge(new LockPlan(Map.of(), Set.of(ProductService.offShelfLockKey(productId))));
        }
    }
}
