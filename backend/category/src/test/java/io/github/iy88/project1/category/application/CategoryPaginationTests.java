package io.github.iy88.project1.category.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.Category;
import io.github.iy88.project1.category.persistence.CategoryName;
import io.github.iy88.project1.category.persistence.CategoryNameRepository;
import io.github.iy88.project1.category.persistence.CategoryRepository;
import io.github.iy88.project1.core.AuditStore;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.transaction.PlatformTransactionManager;

class CategoryPaginationTests {
    private final CategoryRepository categories = mock(CategoryRepository.class);
    private final CategoryNameRepository names = mock(CategoryNameRepository.class);
    private final ObjectProvider<CategoryProductVisibility> productVisibility = mock(ObjectProvider.class);
    private final CategoryService service = new CategoryService(categories, names,
            new CategorySettings(80, 200), productVisibility, mock(PlatformTransactionManager.class),
            mock(AuditStore.class));

    @Test
    void adminListUsesTheRequestedPageAndReturnsTheWholeDirectoryCount() {
        var category = mock(Category.class);
        var main = mock(CategoryName.class);
        var request = PageRequest.of(1, 20);
        when(category.id()).thenReturn(42L);
        when(category.state()).thenReturn("active");
        when(category.createdAt()).thenReturn(Instant.parse("2026-11-26T00:00:00Z"));
        when(main.id()).thenReturn(7L);
        when(main.name()).thenReturn("二手教材");
        when(main.nameKind()).thenReturn("main");
        when(main.active()).thenReturn(true);
        when(names.findByCategoryIdOrderByIdAsc(42L)).thenReturn(List.of(main));
        when(categories.findByDeletedAtIsNullOrderByIdAsc(request))
                .thenReturn(new PageImpl<>(List.of(category), request, 41));

        var result = service.listAdmin(2, 20);

        assertThat(result.page()).isEqualTo(2);
        assertThat(result.pageSize()).isEqualTo(20);
        assertThat(result.total()).isEqualTo(41);
        assertThat(result.items()).singleElement().satisfies(item -> {
            assertThat(item.id()).isEqualTo("42");
            assertThat(item.mainName()).isEqualTo("二手教材");
        });
        verify(categories).findByDeletedAtIsNullOrderByIdAsc(request);
    }
}
