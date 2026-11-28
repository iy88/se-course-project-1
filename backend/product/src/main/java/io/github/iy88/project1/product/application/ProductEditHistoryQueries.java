package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.ProductSettings;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductEditHistoryRepository;
import io.github.iy88.project1.product.persistence.ProductRepository;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;

/**
 * Read side of product edit history: the seller's full history, a buyer's request-scoped history
 * and the case-scoped correction history. Authorization and the output projection stay in this
 * query so callers cannot widen the visible range.
 *
 * <p>The public entry points and their Spring transaction annotations stay on {@link ProductService};
 * this query owns no transaction annotations so the existing overload self-invocation keeps its
 * current proxy behavior.
 */
public class ProductEditHistoryQueries {
    private final ProductRepository products;
    private final ProductEditHistoryRepository edits;
    private final ProductTradeHistory tradeHistory;
    private final ProductSettings settings;
    private final CaseCommentAccess cases;

    public ProductEditHistoryQueries(ProductRepository products, ProductEditHistoryRepository edits,
                                     ProductTradeHistory tradeHistory, ProductSettings settings,
                                     CaseCommentAccess cases) {
        this.products = products;
        this.edits = edits;
        this.tradeHistory = tradeHistory;
        this.settings = settings;
        this.cases = cases;
    }

    /**
     * Seller reads the full history. A buyer reads only the changes from their own request time
     * onward, optionally narrowed to one exact trade, with administrator reasons removed.
     */
    public ProductService.PageResult<ProductService.EditView> editHistory(long viewerId, long productId, Long tradeId,
                                                                         Integer page, Integer pageSize) {
        Product product = products.findById(productId).filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        boolean seller = product.sellerAccountId() == viewerId;
        ProductTradeHistory.BuyerScope buyerScope = seller ? null
                : tradeHistory.buyerScope(productId, viewerId, tradeId)
                        .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        int currentPage = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (currentPage < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        Pageable pageable = PageRequest.of(currentPage - 1, size);
        var pageResult = seller
                ? edits.findByProductIdOrderByEditedAtDescIdDesc(productId, pageable)
                : edits.findBuyerHistory(productId, buyerScope.requestedAt(), pageable);
        List<ProductService.EditView> items = pageResult.getContent().stream()
                .map(edit -> seller
                        ? new ProductService.EditView(Long.toString(edit.id()), edit.editedAt(), edit.operatorKind(),
                                edit.editKind(), edit.beforeContent(), edit.afterContent(), edit.reason())
                        : new ProductService.EditView(Long.toString(edit.id()), edit.editedAt(), edit.operatorKind(),
                                edit.editKind(), buyerContent(edit.beforeContent()),
                                buyerContent(edit.afterContent()), null))
                .toList();
        return new ProductService.PageResult<>(items, currentPage, size, pageResult.getTotalElements());
    }

    public ProductService.PageResult<ProductService.EditView> caseEditHistory(long managerId, long productId,
                                                                             long caseId, Integer page,
                                                                             Integer pageSize) {
        if (!cases.claimedForProduct(managerId, caseId, productId)) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        int currentPage = page == null ? 1 : page;
        int size = pageSize == null ? settings.pageSize() : pageSize;
        if (currentPage < 1 || size < 1 || size > settings.pageSizeMax()) {
            throw new BusinessError("INPUT_INVALID", 422, "分页参数无效");
        }
        var result = edits.findByProductIdAndBasisTypeAndBasisIdOrderByEditedAtDescIdDesc(
                productId, "case", caseId, PageRequest.of(currentPage - 1, size));
        List<ProductService.EditView> items = result.getContent().stream()
                .map(edit -> new ProductService.EditView(Long.toString(edit.id()), edit.editedAt(), edit.operatorKind(),
                        edit.editKind(), buyerContent(edit.beforeContent()), buyerContent(edit.afterContent()),
                        edit.reason()))
                .toList();
        return new ProductService.PageResult<>(items, currentPage, size, result.getTotalElements());
    }

    private static Map<String, Object> buyerContent(Map<String, Object> content) {
        Map<String, Object> allowed = new LinkedHashMap<>();
        for (String key : List.of("title", "description", "price_cents", "image_file_ids", "category_ids")) {
            if (content != null && content.containsKey(key)) {
                allowed.put(key, content.get(key));
            }
        }
        return allowed;
    }
}
