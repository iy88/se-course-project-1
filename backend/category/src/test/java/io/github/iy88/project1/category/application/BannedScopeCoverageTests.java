package io.github.iy88.project1.category.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.BannedItem;
import io.github.iy88.project1.category.persistence.BannedItemRepository;
import io.github.iy88.project1.category.persistence.BannedScopeState;
import io.github.iy88.project1.category.persistence.BannedScopeStateRepository;
import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class BannedScopeCoverageTests {
    private final BannedItemRepository items = mock(BannedItemRepository.class);
    private final BannedScopeStateRepository states = mock(BannedScopeStateRepository.class);
    private final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);
    private final BannedScopeService service =
            new BannedScopeService(items, states, new CategorySettings(50, 200), transactions);

    @Test
    void rejectsReplacementThatOmitsRequiredGroupsBeforeWriting() {
        prepareOneRequiredItem();
        when(items.save(any())).thenAnswer(call -> {
            BannedItem saved = call.getArgument(0);
            ReflectionTestUtils.setField(saved, "id", 9L);
            return saved;
        });
        assertIncomplete(() -> service.replace(7L, List.of(
                new BannedScopeService.Input(null, "legal_prohibited", "Required item", 1))));
        verifyNoInteractions(items, states, transactions);
    }

    @Test
    void rejectsRepeatedIdBeforeOneItemCanStandInForMultipleGroups() {
        assertThatThrownBy(() -> service.replace(7L, List.of(
                new BannedScopeService.Input("5", "legal_prohibited", "Required item", 1),
                new BannedScopeService.Input("5", "dangerous_controlled", "Another required item", 2))))
                .isInstanceOfSatisfying(BusinessError.class, error ->
                        assertThat(error.code()).isEqualTo("INPUT_INVALID"));
        verifyNoInteractions(items, states, transactions);
    }

    @Test
    void rejectsDeletingTheLastItemInARequiredGroupEvenWhenOtherGroupsRemain() {
        prepareOneRequiredItem();
        assertIncomplete(() -> service.delete(7L));
    }

    @Test
    void rejectsMovingTheLastItemOutOfARequiredGroup() {
        prepareOneRequiredItem();
        assertIncomplete(() -> service.update(7L, 7L,
                new BannedScopeService.ItemInput("other", "Moved item", 1)));
    }

    private void prepareOneRequiredItem() {
        var item = new BannedItem("legal_prohibited", "Required item", 1, 7L, Instant.now());
        var other = new BannedItem("other", "Other item", 2, 7L, Instant.now());
        ReflectionTestUtils.setField(item, "id", 7L);
        ReflectionTestUtils.setField(other, "id", 8L);
        when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        when(states.lock()).thenReturn(Optional.of(mock(BannedScopeState.class)));
        when(items.findById(7L)).thenReturn(Optional.of(item));
        when(items.findByDeletedAtIsNullOrderByDisplayOrderAscIdAsc()).thenReturn(List.of(item, other));
    }

    private static void assertIncomplete(Runnable mutation) {
        assertThatThrownBy(mutation::run).isInstanceOfSatisfying(BusinessError.class, error ->
                {
                    assertThat(error.code()).isEqualTo("BANNED_SCOPE_INCOMPLETE");
                    assertThat(error.status()).isEqualTo(422);
                });
    }
}
