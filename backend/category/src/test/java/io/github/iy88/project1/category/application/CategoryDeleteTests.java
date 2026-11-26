package io.github.iy88.project1.category.application;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.Category;
import io.github.iy88.project1.category.persistence.CategoryNameRepository;
import io.github.iy88.project1.category.persistence.CategoryRepository;
import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

@ExtendWith(MockitoExtension.class)
class CategoryDeleteTests {
    private static final long CATEGORY_ID = 42;
    private static final Instant CREATED_AT = Instant.parse("2026-11-24T00:00:00Z");

    @Mock
    CategoryRepository categories;
    @Mock
    CategoryNameRepository names;
    @Mock
    ObjectProvider<CategoryProductVisibility> productVisibility;
    @Mock
    CategoryProductVisibility visibility;
    @Mock
    PlatformTransactionManager transactions;

    private CategoryService service;

    @BeforeEach
    void setUp() {
        when(transactions.getTransaction(any())).thenAnswer(call -> new SimpleTransactionStatus());
        service = new CategoryService(categories, names, new CategorySettings(80, 200),
                productVisibility, transactions);
    }

    @Test
    void secondDeleteSucceedsWithoutRepeatingBusinessWrites() {
        var category = new Category(7, CREATED_AT);
        when(categories.lockById(CATEGORY_ID)).thenReturn(Optional.of(category));
        when(productVisibility.getIfAvailable()).thenReturn(visibility);
        when(visibility.associatedProductCount(CATEGORY_ID)).thenReturn(0L);

        service.delete(CATEGORY_ID);
        Instant firstDeletedAt = category.deletedAt();
        assertNotNull(firstDeletedAt);

        assertDoesNotThrow(() -> service.delete(CATEGORY_ID));
        assertEquals(firstDeletedAt, category.deletedAt());
        verify(categories, times(2)).lockById(CATEGORY_ID);
        verify(categories).save(category);
        verify(names).deactivateAll(CATEGORY_ID, firstDeletedAt);
        verify(visibility).associatedProductCount(CATEGORY_ID);
        verifyNoMoreInteractions(categories, names, visibility);
    }

    @Test
    void missingCategoryStillReturnsNotFound() {
        when(categories.lockById(CATEGORY_ID)).thenReturn(Optional.empty());

        BusinessError error = assertThrows(BusinessError.class, () -> service.delete(CATEGORY_ID));

        assertEquals(404, error.status());
        assertEquals("RESOURCE_NOT_VISIBLE", error.code());
        verify(categories, never()).save(any());
        verifyNoInteractions(names, productVisibility);
    }

    @Test
    void associatedCategoryStillCannotBeDeleted() {
        var category = new Category(7, CREATED_AT);
        when(categories.lockById(CATEGORY_ID)).thenReturn(Optional.of(category));
        when(productVisibility.getIfAvailable()).thenReturn(visibility);
        when(visibility.associatedProductCount(CATEGORY_ID)).thenReturn(1L);

        BusinessError error = assertThrows(BusinessError.class, () -> service.delete(CATEGORY_ID));

        assertEquals(409, error.status());
        assertEquals("CATEGORY_NOT_DELETABLE", error.code());
        assertNull(category.deletedAt());
        verify(categories, never()).save(any());
        verifyNoInteractions(names);
    }

    @Test
    void renameStillRejectsDeletedCategory() {
        var category = new Category(7, CREATED_AT);
        category.delete(CREATED_AT.plusSeconds(1));
        when(categories.lockById(CATEGORY_ID)).thenReturn(Optional.of(category));

        BusinessError error = assertThrows(BusinessError.class, () -> service.rename(CATEGORY_ID, "二手教材"));

        assertEquals(404, error.status());
        assertEquals("RESOURCE_NOT_VISIBLE", error.code());
        verify(categories, never()).save(any());
        verifyNoInteractions(names, productVisibility);
    }
}
