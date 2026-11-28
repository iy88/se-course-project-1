package io.github.iy88.project1.category.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.category.CategorySettings;
import io.github.iy88.project1.category.persistence.Category;
import io.github.iy88.project1.category.persistence.CategoryName;
import io.github.iy88.project1.category.persistence.CategoryNameRepository;
import io.github.iy88.project1.category.persistence.CategoryRepository;
import io.github.iy88.project1.core.AuditActions;
import io.github.iy88.project1.core.AuditContext;
import io.github.iy88.project1.core.AuditStore;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class CategoryAuditTests {
    private static final long MANAGER = 9L;
    private static final long CATEGORY = 42L;
    private static final Instant NOW = Instant.parse("2026-11-26T04:00:00Z");

    private final CategoryRepository categories = mock(CategoryRepository.class);
    private final CategoryNameRepository names = mock(CategoryNameRepository.class);
    private final ObjectProvider<CategoryProductVisibility> productVisibility =
            mock();
    private final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);
    private final AuditStore auditRecords = mock(AuditStore.class);
    private final AuditContext context = new AuditContext(new ExecutionContext(UUID.randomUUID(),
            ExecutionContext.ActorKind.ACCOUNT, Long.toString(MANAGER), UUID.randomUUID(), null, 1L, "cfg"),
            UUID.randomUUID());
    private CategoryService service;

    @BeforeEach
    void setUp() {
        when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        service = new CategoryService(categories, names, new CategorySettings(80, 200), productVisibility,
                transactions, auditRecords);
    }

    @Test
    void createAuditsTheNewCategoryWithTheActualManagerAndTarget() {
        Category category = mock(Category.class);
        when(category.id()).thenReturn(CATEGORY);
        when(category.state()).thenReturn("active");
        when(category.createdAt()).thenReturn(NOW);
        when(categories.save(any())).thenReturn(category);

        CategoryName main = mock(CategoryName.class);
        when(main.id()).thenReturn(7L);
        when(main.name()).thenReturn("二手教材");
        when(main.nameKind()).thenReturn("main");
        when(main.active()).thenReturn(true);
        when(names.save(any())).thenReturn(main);
        when(names.findByCategoryIdOrderByIdAsc(CATEGORY)).thenReturn(List.of(main));

        service.create(MANAGER, "二手教材", context);

        var facts = ArgumentCaptor.<Map<String, ?>>captor();
        verify(auditRecords).record(eq(context), eq(AuditActions.CATEGORY_CREATED),
                eq(new ResourceRef("category", CATEGORY)), isNull(), facts.capture());
        assertThat(facts.getValue().get("main_name")).isEqualTo("二手教材");
        assertThat(facts.getValue().get("category_name_id")).isEqualTo("7");
        assertThat(facts.getValue().get("state")).isEqualTo("active");
    }

    @Test
    void disableAuditsTheStateChange() {
        Category category = mock(Category.class);
        when(category.id()).thenReturn(CATEGORY);
        when(category.state()).thenReturn("active", "disabled");
        when(category.createdAt()).thenReturn(NOW);
        when(categories.lockById(CATEGORY)).thenReturn(Optional.of(category));
        when(categories.save(any())).thenReturn(category);
        when(names.findByCategoryIdOrderByIdAsc(CATEGORY)).thenReturn(List.of());

        service.disable(CATEGORY, context);

        var facts = ArgumentCaptor.<Map<String, ?>>captor();
        verify(auditRecords).record(eq(context), eq(AuditActions.CATEGORY_DISABLED),
                eq(new ResourceRef("category", CATEGORY)), isNull(), facts.capture());
        assertThat(facts.getValue().get("previous_state")).isEqualTo("active");
        assertThat(facts.getValue().get("current_state")).isEqualTo("disabled");
    }

    @Test
    void auditFailurePropagatesAndRollsBackTheCategoryTransaction() {
        Category category = mock(Category.class);
        when(category.id()).thenReturn(CATEGORY);
        when(category.state()).thenReturn("active", "disabled");
        when(category.createdAt()).thenReturn(NOW);
        when(categories.lockById(CATEGORY)).thenReturn(Optional.of(category));
        when(categories.save(any())).thenReturn(category);
        when(names.findByCategoryIdOrderByIdAsc(CATEGORY)).thenReturn(List.of());
        when(auditRecords.record(any(), any(), any(), any(), any()))
                .thenThrow(new IllegalStateException("audit unavailable"));

        assertThatThrownBy(() -> service.disable(CATEGORY, context))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("audit unavailable");
        verify(transactions).rollback(any());
    }
}
