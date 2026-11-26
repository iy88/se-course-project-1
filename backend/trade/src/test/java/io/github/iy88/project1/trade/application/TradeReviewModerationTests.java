package io.github.iy88.project1.trade.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class TradeReviewModerationTests {
    private static final long REVIEW = 501L;
    private static final long TRADE = 901L;
    private static final long AUTHOR = 8001L;
    private static final long MANAGER = 1001L;
    private static final Instant NOW = Instant.parse("2026-11-25T00:00:00Z");

    private final TradeRepository repository = mock(TradeRepository.class);
    private TradeReviewModeration moderation;

    @BeforeEach
    void setUp() {
        moderation = new TradeReviewModeration(repository);
    }

    @Test
    void targetLookupReturnsTheTradeAndAuthorBeforeLocking() {
        when(repository.reviewModerationFact(REVIEW)).thenReturn(Optional.of(
                new TradeRepository.ReviewModerationFact(REVIEW, TRADE, AUTHOR, true, null)));

        var target = moderation.target(REVIEW);

        assertThat(target).get().satisfies(found -> {
            assertThat(found.reviewId()).isEqualTo(REVIEW);
            assertThat(found.tradeId()).isEqualTo(TRADE);
            assertThat(found.authorAccountId()).isEqualTo(AUTHOR);
        });
    }

    @Test
    void snapshotKeepsTheRetainedBodyForTheCaseTargetRead() {
        when(repository.reviewSnapshot(REVIEW)).thenReturn(Optional.of(
                new TradeRepository.ReviewSnapshot(REVIEW, TRADE, AUTHOR, "评价正文", 5,
                        "removed_by_admin", NOW, NOW)));

        var snapshot = moderation.snapshot(REVIEW);

        assertThat(snapshot).get().satisfies(fact -> {
            assertThat(fact.reviewId()).isEqualTo(REVIEW);
            assertThat(fact.tradeId()).isEqualTo(TRADE);
            assertThat(fact.authorAccountId()).isEqualTo(AUTHOR);
            assertThat(fact.body()).isEqualTo("评价正文");
            assertThat(fact.rating()).isEqualTo(5);
            assertThat(fact.state()).isEqualTo(TradeReviewModeration.REMOVED_BY_ADMIN);
            assertThat(fact.removedAt()).isEqualTo(NOW);
        });
        verify(repository, never()).markReviewRemoved(anyLong(), anyLong(), anyLong(), any(), any(), any());
    }

    @Test
    void removalRequiresTheTradeLockAndRecordsOnlyModerationFields() {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context(MANAGER));
        when(repository.reviewModerationFact(REVIEW)).thenReturn(Optional.of(
                new TradeRepository.ReviewModerationFact(REVIEW, TRADE, AUTHOR, true, null)));
        when(repository.markReviewRemoved(REVIEW, TRADE, MANAGER, "spam", "case:1", NOW)).thenReturn(true);

        var removed = moderation.removeLocked(transaction, REVIEW, TRADE, "spam", "case:1", NOW);

        verify(transaction).requireLocked(TradeReviewModeration.tradeLockKey(TRADE));
        verify(repository).markReviewRemoved(REVIEW, TRADE, MANAGER, "spam", "case:1", NOW);
        assertThat(removed.reviewId()).isEqualTo("501");
        assertThat(removed.authorAccountId()).isEqualTo(AUTHOR);
        assertThat(removed.previousState()).isEqualTo(TradeReviewModeration.PUBLISHED);
        assertThat(removed.currentState()).isEqualTo(TradeReviewModeration.REMOVED_BY_ADMIN);
        assertThat(removed.status()).isEqualTo(TradeReviewModeration.REMOVED_BY_ADMIN);
    }

    @Test
    void anOldHiddenReviewStaysHiddenAndStillGetsItsModerationRecord() {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context(MANAGER));
        when(repository.reviewModerationFact(REVIEW)).thenReturn(Optional.of(
                new TradeRepository.ReviewModerationFact(REVIEW, TRADE, AUTHOR, false, null)));
        when(repository.markReviewRemoved(REVIEW, TRADE, MANAGER, "spam", "case:1", NOW)).thenReturn(true);

        var removed = moderation.removeLocked(transaction, REVIEW, TRADE, "spam", "case:1", NOW);

        assertThat(removed.previousState()).isEqualTo(TradeReviewModeration.HIDDEN);
        assertThat(removed.currentState()).isEqualTo(TradeReviewModeration.REMOVED_BY_ADMIN);
    }

    @Test
    void removalRejectsMissingStaleAndAlreadyRemovedReviews() {
        var transaction = mock(WriteTransaction.class);
        when(transaction.context()).thenReturn(context(MANAGER));
        when(repository.reviewModerationFact(REVIEW)).thenReturn(Optional.empty());
        assertFailure(transaction, "CONTENT_NOT_FOUND");

        when(repository.reviewModerationFact(REVIEW)).thenReturn(Optional.of(
                new TradeRepository.ReviewModerationFact(REVIEW, TRADE + 1, AUTHOR, true, null)));
        assertFailure(transaction, "TARGET_STATE_CONFLICT");

        when(repository.reviewModerationFact(REVIEW)).thenReturn(Optional.of(
                new TradeRepository.ReviewModerationFact(REVIEW, TRADE, AUTHOR, false, NOW)));
        assertFailure(transaction, "TARGET_STATE_CONFLICT");
        verify(repository, never()).markReviewRemoved(anyLong(), anyLong(), anyLong(), any(), any(), any());
    }

    private void assertFailure(WriteTransaction transaction, String code) {
        assertThatThrownBy(() -> moderation.removeLocked(transaction, REVIEW, TRADE, "spam", "case:1", NOW))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo(code));
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), UUID.randomUUID(), null, 1L, "review-moderation-test");
    }
}
