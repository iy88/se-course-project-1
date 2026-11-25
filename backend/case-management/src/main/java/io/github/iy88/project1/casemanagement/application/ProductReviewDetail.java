package io.github.iy88.project1.casemanagement.application;

import java.net.URI;
import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Product-owned review detail; the case claim is attached by the application. */
public record ProductReviewDetail(long auditId, long productId, long caseId, String status,
                                  Instant submittedAt, Seller seller, CurrentContent currentContent,
                                  CategoryApplicationView categoryApplication, List<BannedItem> bannedScope,
                                  ReviewResult reviewResult) {
    public ProductReviewDetail {
        if (auditId <= 0 || productId <= 0 || caseId <= 0) {
            throw new IllegalArgumentException("Invalid review detail ids");
        }
        Objects.requireNonNull(status);
        Objects.requireNonNull(submittedAt);
        Objects.requireNonNull(seller);
        Objects.requireNonNull(currentContent);
        bannedScope = List.copyOf(bannedScope);
    }

    public record Seller(long id, String displayName) {
        public Seller {
            if (id <= 0) {
                throw new IllegalArgumentException("Invalid seller id");
            }
            Objects.requireNonNull(displayName);
        }
    }

    public record CurrentContent(String title, String description, List<Image> images, long priceCents,
                                 List<Category> categories, int contentVersion) {
        public CurrentContent {
            Objects.requireNonNull(title);
            Objects.requireNonNull(description);
            images = List.copyOf(images);
            categories = List.copyOf(categories);
            if (priceCents < 0 || contentVersion <= 0) {
                throw new IllegalArgumentException("Invalid product content");
            }
        }
    }

    public record Image(long fileId, URI url, Instant expiresAt) {}

    public record Category(long id, String name) {}

    public record BannedItem(long id, String group, String content) {
        public BannedItem {
            if (id <= 0) {
                throw new IllegalArgumentException("Invalid banned item id");
            }
            Objects.requireNonNull(group);
            Objects.requireNonNull(content);
        }
    }

    public record ReviewResult(String decision, String reason, int reviewedContentVersion,
                               Instant decidedAt, long decidedBy) {
        public ReviewResult {
            Objects.requireNonNull(decision);
            if (reviewedContentVersion <= 0 || decidedBy <= 0) {
                throw new IllegalArgumentException("Invalid review result");
            }
            Objects.requireNonNull(decidedAt);
        }
    }
}
