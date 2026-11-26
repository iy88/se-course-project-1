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
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.UriComponentsBuilder;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/products")
@Profile("infrastructure")
class ProductController {
    private final ProductService products;
    private final CurrentAccount current;
    private final ApiRequestContext requestContext;
    private final ProductOffShelfWrite offShelfWrites;

    ProductController(ProductService products, CurrentAccount current, ApiRequestContext requestContext,
                      ProductOffShelfWrite offShelfWrites) {
        this.products = products;
        this.current = current;
        this.requestContext = requestContext;
        this.offShelfWrites = offShelfWrites;
    }

    @PostMapping
    ResponseEntity<ProductService.ProductDetail> create(@RequestBody CreateRequest body, HttpServletRequest request) {
        var identity = current.require(request);
        var created = products.create(identity.account().id(), new ProductService.CreateCommand(
                body.title(), body.description(), body.imageFileIds(), body.priceCents(), body.categoryIds(),
                body.categoryApplication() == null ? null : body.categoryApplication().proposedName()));
        var location = UriComponentsBuilder.fromPath("/api/v1/products/{id}")
                .buildAndExpand(created.id()).toUriString();
        return ResponseEntity.status(201).location(java.net.URI.create(location))
                .cacheControl(CacheControl.noStore())
                .body(created);
    }

    @GetMapping
    ResponseEntity<ProductService.PageResult<ProductService.ProductSummary>> search(
            @RequestParam(required = false) String keyword,
            @RequestParam(value = "category_ids", required = false) List<String> categoryIds,
            @RequestParam(value = "min_price_cents", required = false) Long minPrice,
            @RequestParam(value = "max_price_cents", required = false) Long maxPrice,
            @RequestParam(required = false) Integer page,
            @RequestParam(value = "page_size", required = false) Integer pageSize,
            HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.search(identity.account().id(), keyword, categoryIds, minPrice, maxPrice, page,
                        pageSize));
    }

    @GetMapping("/{productId}")
    ResponseEntity<ProductService.ProductDetail> detail(@PathVariable String productId, HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.detail(identity.account().id(), id(productId)));
    }

    @PatchMapping("/{productId}")
    ResponseEntity<ProductService.ProductDetail> edit(@PathVariable String productId, @RequestBody EditRequest body,
                                                      HttpServletRequest request) {
        var identity = current.require(request);
        var updated = products.edit(identity.account().id(), id(productId), new ProductService.EditCommand(
                body.title(), body.description(), body.imageFileIds(), body.priceCents(), body.categoryIds(),
                body.categoryApplication() == null ? null : body.categoryApplication().proposedName(),
                body.expectedVersion()), context(identity, request));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(updated);
    }

    @PostMapping("/{productId}/review-submissions")
    ResponseEntity<ProductService.Resubmitted> resubmit(@PathVariable String productId,
                                                        @RequestBody VersionRequest body,
                                                        HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(products.resubmit(identity.account().id(), id(productId), body.expectedVersion()));
    }

    @PostMapping("/{productId}/withdrawal")
    ResponseEntity<ProductService.Withdrawn> withdraw(@PathVariable String productId,
                                                      @RequestBody VersionRequest body,
                                                      HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.withdraw(identity.account().id(), id(productId), body.expectedVersion()));
    }

    @PostMapping("/{productId}/off-shelf")
    ResponseEntity<JsonNode> offShelf(@PathVariable String productId,
                                      @RequestHeader("Idempotency-Key") String key,
                                      @RequestBody VersionRequest body,
                                      HttpServletRequest request) {
        var identity = current.require(request);
        var result = offShelfWrites.offShelf(context(identity, request), key, id(productId),
                body.expectedVersion());
        return ResponseEntity.status(result.status()).cacheControl(CacheControl.noStore()).body(result.data());
    }

    @PostMapping("/{productId}/on-shelf")
    ResponseEntity<ProductService.ProductDetail> onShelf(@PathVariable String productId,
                                                         @RequestBody VersionRequest body,
                                                         HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.onShelf(identity.account().id(), id(productId), body.expectedVersion()));
    }

    @PostMapping("/{productId}/category-applications")
    ResponseEntity<ProductService.ApplicationCreated> createCategoryApplication(
            @PathVariable String productId, @RequestBody CategoryApplicationRequest body,
            HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                .body(products.createApplication(identity.account().id(), id(productId), body.proposedName()));
    }

    @DeleteMapping("/{productId}/category-application")
    ResponseEntity<Void> withdrawCategoryApplication(@PathVariable String productId, HttpServletRequest request) {
        var identity = current.require(request);
        products.withdrawApplication(identity.account().id(), id(productId));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @GetMapping("/{productId}/edit-history")
    ResponseEntity<ProductService.PageResult<ProductService.EditView>> editHistory(
            @PathVariable String productId, @RequestParam(required = false) Integer page,
            @RequestParam(value = "page_size", required = false) Integer pageSize,
            @RequestParam(value = "trade_id", required = false) String tradeId, HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(products.editHistory(identity.account().id(), id(productId),
                        tradeId == null || tradeId.isBlank() ? null : id(tradeId), page, pageSize));
    }

    private ExecutionContext context(io.github.iy88.project1.account.application.SessionService.Identity identity,
                                     HttpServletRequest request) {
        return requestContext.forActor(request, ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(identity.account().id()), identity.guard().id(), null,
                (long) identity.guard().credentialVersion());
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

    record CategoryApplicationRequest(String proposedName) {
    }

    record CreateRequest(String title, String description, List<String> imageFileIds, Long priceCents,
                         List<String> categoryIds, CategoryApplicationRequest categoryApplication) {
    }

    record EditRequest(String title, String description, List<String> imageFileIds, Long priceCents,
                       List<String> categoryIds, CategoryApplicationRequest categoryApplication,
                       Integer expectedVersion) {
    }

    record VersionRequest(Integer expectedVersion) {
    }
}
