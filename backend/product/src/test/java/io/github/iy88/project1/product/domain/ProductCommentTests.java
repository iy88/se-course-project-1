package io.github.iy88.project1.product.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class ProductCommentTests {
    private static final Instant NOW = Instant.parse("2026-11-23T00:00:00Z");

    @Test
    void derivesStateFromRemovalAndDeletionFacts() {
        assertThat(comment(null, null).state()).isEqualTo(ProductComment.PUBLISHED);
        assertThat(comment(NOW, null).state()).isEqualTo(ProductComment.DELETED_BY_AUTHOR);
        assertThat(comment(NOW, NOW).state()).isEqualTo(ProductComment.REMOVED_BY_ADMIN);
        assertThat(comment(null, NOW).state()).isEqualTo(ProductComment.REMOVED_BY_ADMIN);
    }

    @Test
    void onlyTheAuthorMayDeleteAndRemovalWinsOverDeletion() {
        assertThatThrownBy(() -> comment(null, null).requireDeleteBy(9))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("ACTION_NOT_ALLOWED"));
        assertThatThrownBy(() -> comment(NOW, NOW).requireDeleteBy(7))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("COMMENT_ALREADY_REMOVED"));
        assertThatThrownBy(() -> comment(null, NOW).requireRemovable())
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));
    }

    @Test
    void repliesAreOneLevelAndMustTargetPublishedTopLevelComments() {
        comment(null, null).requireReplyTarget();
        assertThatThrownBy(() -> reply().requireReplyTarget())
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));
        assertThatThrownBy(() -> comment(NOW, null).requireReplyTarget())
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("STATE_CONFLICT"));
    }

    private static ProductComment comment(Instant deletedAt, Instant removedAt) {
        return new ProductComment(1, 10, 7, null, "Hello", NOW, deletedAt, removedAt,
                removedAt == null ? null : "spam", removedAt == null ? null : "case:1");
    }

    private static ProductComment reply() {
        return new ProductComment(2, 10, 8, 1L, "Thanks", NOW.plusSeconds(1), null, null, null, null);
    }
}
