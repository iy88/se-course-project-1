package io.github.iy88.project1.api.account;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductService;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure")
class AccountResourcesController {
    private static final Set<String> OTHER_KINDS = Set.of("trade", "favorite", "evaluation", "report");

    private final ProductService products;
    private final CurrentAccount current;

    AccountResourcesController(ProductService products, CurrentAccount current) {
        this.products = products;
        this.current = current;
    }

    @GetMapping("/api/v1/account/resources")
    ResponseEntity<ProductService.MyResources> list(@RequestParam(required = false) String kind,
                                                    @RequestParam(required = false) String state,
                                                    @RequestParam(required = false) Integer page,
                                                    @RequestParam(name = "page_size", required = false)
                                                    Integer pageSize,
                                                    @RequestParam(required = false) String role,
                                                    @RequestParam(required = false) String direction,
                                                    HttpServletRequest request) {
        var identity = current.require(request);
        if (!"product".equals(kind)) {
            if (kind == null || !OTHER_KINDS.contains(kind)) {
                throw new BusinessError("INPUT_INVALID", 422, "资源类型无效");
            }
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该资源类型暂未接入");
        }
        if (role != null || direction != null) {
            throw new BusinessError("INPUT_INVALID", 422, "商品资源不接受 role 或 direction");
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.myResources(identity.account().id(), state, page, pageSize));
    }
}
