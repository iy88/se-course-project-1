package io.github.iy88.project1.api.product;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.product.application.ProductService;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Administrator product operations that the product module owns end to end. */
@RestController
@RequestMapping("/api/v1/admin/products")
@Profile("infrastructure")
class AdminProductController {
    private final ProductService products;
    private final CurrentAccount current;
    private final ApiRequestContext requestContext;

    AdminProductController(ProductService products, CurrentAccount current, ApiRequestContext requestContext) {
        this.products = products;
        this.current = current;
        this.requestContext = requestContext;
    }

    /** API-PRD-032; the claimed-case basis is validated against the product in the service. */
    @PostMapping("/{productId}/category-correction")
    ResponseEntity<ProductService.CorrectionResult> correctCategory(@PathVariable String productId,
                                                                   @RequestBody CorrectionRequest body,
                                                                   HttpServletRequest request) {
        var identity = current.require(request);
        if (!"manager".equals(identity.account().role())) {
            throw new BusinessError("ACTION_NOT_ALLOWED", 403, "无管理权限");
        }
        var context = requestContext.forActor(request, ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(identity.account().id()), identity.guard().id(), null,
                (long) identity.guard().credentialVersion());
        var correction = new ProductService.CorrectionCommand(body.categoryIds(), body.reason(),
                body.basisRef() == null ? null : body.basisRef().type(),
                body.basisRef() == null ? 0L : id(body.basisRef().id()));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.correctCategory(identity.account().id(), id(productId), correction, context));
    }

    private static long id(String value) {
        try {
            long id = Long.parseLong(value);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new BusinessError("INPUT_INVALID", 422, "标识无效");
    }

    record CorrectionRequest(List<String> categoryIds, String reason, BasisRef basisRef) {
    }

    record BasisRef(String type, String id) {
    }
}
