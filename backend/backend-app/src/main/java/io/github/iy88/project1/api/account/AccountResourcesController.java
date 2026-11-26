package io.github.iy88.project1.api.account;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure")
class AccountResourcesController {
    private final ProductService products;
    private final AccountOwnedQueries queries;
    private final CurrentAccount current;

    AccountResourcesController(ProductService products, AccountOwnedQueries queries, CurrentAccount current) {
        this.products = products;
        this.queries = queries;
        this.current = current;
    }

    @GetMapping("/api/v1/account/overview")
    ResponseEntity<AccountOwnedQueries.MyOverview> overview(HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(queries.overview(identity.account().id()));
    }

    @GetMapping("/api/v1/account/todos")
    ResponseEntity<AccountOwnedQueries.MyTodoPage> todos(@RequestParam(required = false) String kind,
                                                         @RequestParam(required = false) Integer page,
                                                         @RequestParam(name = "page_size", required = false)
                                                         Integer pageSize,
                                                         HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(queries.todos(identity.account().id(), kind, page, pageSize));
    }

    @GetMapping("/api/v1/account/resources")
    ResponseEntity<?> list(@RequestParam(required = false) String kind,
                           @RequestParam(required = false) String state,
                           @RequestParam(required = false) Integer page,
                           @RequestParam(name = "page_size", required = false) Integer pageSize,
                           @RequestParam(required = false) String role,
                           @RequestParam(required = false) String direction,
                           HttpServletRequest request) {
        var identity = current.require(request);
        long accountId = identity.account().id();
        if (kind == null || kind.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "资源类型无效");
        }
        return switch (kind.trim()) {
            case "product" -> {
                if (hasValue(role) || hasValue(direction)) {
                    throw new BusinessError("INPUT_INVALID", 422, "商品资源不接受 role 或 direction");
                }
                yield ResponseEntity.ok().cacheControl(CacheControl.noStore())
                        .body(products.myResources(accountId, state, page, pageSize));
            }
            case "trade" -> {
                if (hasValue(direction)) {
                    throw new BusinessError("INPUT_INVALID", 422, "交易资源不接受 direction");
                }
                yield ResponseEntity.ok().cacheControl(CacheControl.noStore())
                        .body(queries.tradeResources(accountId, role, state, page, pageSize));
            }
            case "evaluation" -> {
                if (hasValue(role) || hasValue(state)) {
                    throw new BusinessError("INPUT_INVALID", 422, "评价资源不接受 role 或 state");
                }
                yield ResponseEntity.ok().cacheControl(CacheControl.noStore())
                        .body(queries.evaluationResources(accountId, direction, page, pageSize));
            }
            case "report" -> {
                if (hasValue(role)) {
                    throw new BusinessError("INPUT_INVALID", 422, "举报资源不接受 role");
                }
                yield ResponseEntity.ok().cacheControl(CacheControl.noStore())
                        .body(queries.reportResources(accountId, direction, state, page, pageSize));
            }
            default -> throw new BusinessError("INPUT_INVALID", 422, "资源类型无效");
        };
    }

    private static boolean hasValue(String value) {
        return value != null && !value.isBlank();
    }
}
