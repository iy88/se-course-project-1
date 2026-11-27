package io.github.iy88.project1.category.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.BannedItem;
import io.github.iy88.project1.category.persistence.BannedItemRepository;
import io.github.iy88.project1.category.persistence.BannedScopeStateRepository;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;

/**
 * The read-only banned-scope projection is the public publishing precondition. It deliberately
 * has no role filter; authentication remains at the HTTP boundary.
 */
class BannedScopeServiceTests {
    private static final Instant EARLIER = Instant.parse("2026-11-20T00:00:00Z");
    private static final Instant LATER = Instant.parse("2026-11-22T00:00:00Z");

    private final BannedItemRepository items = mock(BannedItemRepository.class);
    private BannedScopeService service;

    @BeforeEach
    void setUp() {
        PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
        service = new BannedScopeService(items, mock(BannedScopeStateRepository.class), new CategorySettings(50, 200), manager);
    }

    @Test
    void viewGroupsCurrentItemsInTheContractOrderAndReportsTheLatestUpdate() {
        when(items.findByDeletedAtIsNullOrderByDisplayOrderAscIdAsc()).thenReturn(List.of(
                item(11L, "other", "Other item", 5, EARLIER),
                item(12L, "medicine_device", "Prescription drug", 2, LATER),
                item(13L, "legal_prohibited", "Stolen goods", 1, EARLIER)));

        BannedScopeService.BannedScopeView view = service.view();

        assertThat(view.updatedAt()).isEqualTo(LATER);
        assertThat(view.groups()).extracting(BannedScopeService.GroupView::group)
                .containsExactly("legal_prohibited", "medicine_device", "other");
        assertThat(view.groups().getFirst().items())
                .extracting(BannedScopeService.ItemView::id)
                .containsExactly("13");
        assertThat(view.groups().get(1).items())
                .extracting(BannedScopeService.ItemView::content)
                .containsExactly("Prescription drug");
    }

    private static BannedItem item(long id, String group, String content, int order, Instant updatedAt) {
        BannedItem item = new BannedItem(group, content, order, 1L, updatedAt);
        ReflectionTestUtils.setField(item, "id", id);
        return item;
    }
}
