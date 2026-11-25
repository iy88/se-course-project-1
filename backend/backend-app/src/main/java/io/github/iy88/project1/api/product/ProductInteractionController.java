package io.github.iy88.project1.api.product;

import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductInteractions;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.UriComponentsBuilder;

/** Product comments, seller replies and personal favourites (API-PRD-024—031). */
@RestController
@Profile("infrastructure")
class ProductInteractionController {
    private final ProductInteractions interactions;
    private final CurrentAccount current;

    ProductInteractionController(ProductInteractions interactions, CurrentAccount current) {
        this.interactions = interactions;
        this.current = current;
    }

    @GetMapping("/api/v1/products/{productId}/comments")
    ResponseEntity<ProductInteractions.CommentPage> listComments(
            @PathVariable String productId,
            @RequestParam(required = false) Integer page,
            @RequestParam(name = "page_size", required = false) Integer pageSize,
            @RequestParam(name = "case_id", required = false) String caseId,
            @RequestParam(name = "anchor_comment_id", required = false) String anchorCommentId,
            HttpServletRequest request) {
        var identity = current.require(request);
        Long claimedCase = caseId == null || caseId.isBlank() ? null : id(caseId, "case_id");
        Long anchor = anchorCommentId == null ? null : id(anchorCommentId, "anchor_comment_id");
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(interactions.listComments(identity.account().id(), id(productId, "product_id"),
                        page, pageSize, claimedCase, anchor));
    }

    @PostMapping("/api/v1/products/{productId}/comments")
    ResponseEntity<ProductInteractions.CommentView> createComment(@PathVariable String productId,
                                                                  @RequestBody CommentRequest body,
                                                                  @RequestHeader("Idempotency-Key") String idempotencyKey,
                                                                  HttpServletRequest request) {
        var identity = current.require(request);
        long product = id(productId, "product_id");
        var created = interactions.createComment(identity.account().id(), product, body.body());
        return ResponseEntity.status(201).location(commentLocation(product, created.id()))
                .cacheControl(CacheControl.noStore()).body(created);
    }

    @PostMapping("/api/v1/products/{productId}/comments/{commentId}/replies")
    ResponseEntity<ProductInteractions.CommentView> reply(@PathVariable String productId,
                                                          @PathVariable String commentId,
                                                          @RequestBody CommentRequest body,
                                                          @RequestHeader("Idempotency-Key") String idempotencyKey,
                                                          HttpServletRequest request) {
        var identity = current.require(request);
        long product = id(productId, "product_id");
        var created = interactions.replyToComment(identity.account().id(), product,
                id(commentId, "comment_id"), body.body());
        return ResponseEntity.status(201).location(commentLocation(product, created.id()))
                .cacheControl(CacheControl.noStore()).body(created);
    }

    @DeleteMapping("/api/v1/products/{productId}/comments/{commentId}")
    ResponseEntity<Void> deleteComment(@PathVariable String productId, @PathVariable String commentId,
                                       @RequestHeader("Idempotency-Key") String idempotencyKey,
                                       HttpServletRequest request) {
        var identity = current.require(request);
        interactions.deleteComment(identity.account().id(), id(productId, "product_id"),
                id(commentId, "comment_id"));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    @GetMapping(path = "/api/v1/account/resources", params = "kind=favorite")
    ResponseEntity<ProductInteractions.FavoriteResources> listFavoriteResources(
            @RequestParam(required = false) String state,
            @RequestParam(required = false) Integer page,
            @RequestParam(name = "page_size", required = false) Integer pageSize,
            @RequestParam(required = false) String role,
            @RequestParam(required = false) String direction,
            HttpServletRequest request) {
        var identity = current.require(request);
        if (role != null || direction != null) {
            throw new BusinessError("INPUT_INVALID", 422, "收藏资源不接受 role 或 direction");
        }
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(interactions.listFavoriteResources(identity.account().id(), state, page, pageSize));
    }

    @GetMapping("/api/v1/me/favorites")
    ResponseEntity<ProductInteractions.FavoritePage> listFavorites(
            @RequestParam(required = false) Integer page,
            @RequestParam(name = "page_size", required = false) Integer pageSize,
            HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(interactions.listFavorites(identity.account().id(), page, pageSize));
    }

    @GetMapping("/api/v1/me/favorites/{productId}")
    ResponseEntity<ProductInteractions.FavoriteStatus> favoriteStatus(@PathVariable String productId,
                                                                      HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(interactions.favoriteStatus(identity.account().id(), id(productId, "product_id")));
    }

    @PutMapping("/api/v1/me/favorites/{productId}")
    ResponseEntity<ProductInteractions.FavoriteStatus> addFavorite(@PathVariable String productId,
                                                                   @RequestHeader("Idempotency-Key") String idempotencyKey,
                                                                   HttpServletRequest request) {
        var identity = current.require(request);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(interactions.addFavorite(identity.account().id(), id(productId, "product_id")));
    }

    @DeleteMapping("/api/v1/me/favorites/{productId}")
    ResponseEntity<Void> removeFavorite(@PathVariable String productId,
                                        @RequestHeader("Idempotency-Key") String idempotencyKey,
                                        HttpServletRequest request) {
        var identity = current.require(request);
        interactions.removeFavorite(identity.account().id(), id(productId, "product_id"));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    private static URI commentLocation(long productId, String commentId) {
        return URI.create(UriComponentsBuilder.fromPath("/api/v1/products/{product}/comments/{comment}")
                .buildAndExpand(productId, commentId).toUriString());
    }

    private static long id(String value, String field) {
        try {
            long id = Long.parseLong(value);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new BusinessError("INPUT_INVALID", 422, field + " 无效");
    }

    record CommentRequest(String body) {
    }
}
