package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductAudit;
import io.github.iy88.project1.product.persistence.ProductAuditRepository;
import io.github.iy88.project1.product.persistence.ProductRepository;
import org.springframework.beans.factory.ObjectProvider;

final class ProductWriteSupport {
    private ProductWriteSupport() {
    }

    static Product lockForSeller(ProductRepository products, long sellerId, long productId) {
        Product product = products.lockById(productId)
                .filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        if (product.sellerAccountId() != sellerId) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        return product;
    }

    static void requireVersion(Product product, Integer expectedVersion) {
        if (expectedVersion == null || expectedVersion != product.contentVersion()) {
            throw new BusinessError("VERSION_CONFLICT", 409, "商品内容已被更新");
        }
    }

    static void requirePublishOrDelistable(ObjectProvider<ProductTradeFreeze> tradeFreezes, long sellerId) {
        ProductTradeFreeze freezes = tradeFreezes.getIfAvailable();
        if (freezes == null) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "交易资格暂不可用");
        }
        if (freezes.isPartyFrozen(sellerId)) {
            throw new BusinessError("TRADE_FROZEN", 409, "交易冻结期间不能发布、上架或下架商品");
        }
    }

    static ProductAudit latestAudit(ProductAuditRepository audits, long productId) {
        return audits.findTopByProductIdOrderBySequenceNoDesc(productId).orElse(null);
    }
}
