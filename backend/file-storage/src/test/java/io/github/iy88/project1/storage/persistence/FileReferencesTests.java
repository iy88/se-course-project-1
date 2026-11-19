package io.github.iy88.project1.storage.persistence;

import jakarta.persistence.EntityManager;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class FileReferencesTests {
    private final FileRecordRepository files = mock(FileRecordRepository.class);
    private final FileReferenceRepository references = mock(FileReferenceRepository.class);
    private final EntityManager entityManager = mock(EntityManager.class);
    private final FileReferences service = new FileReferences(files, references, entityManager);

    @Test
    void locksDistinctFileIdsInAscendingOrder() {
        var first = new FileRecord();
        var second = new FileRecord();
        when(files.lockById(4L)).thenReturn(Optional.of(first));
        when(files.lockById(9L)).thenReturn(Optional.of(second));

        service.lockFiles(List.of(9L, 4L, 9L));

        var calls = inOrder(files, entityManager);
        calls.verify(files).lockById(4L);
        calls.verify(entityManager).refresh(first);
        calls.verify(files, times(1)).lockById(9L);
        calls.verify(entityManager).refresh(second);
        calls.verifyNoMoreInteractions();
    }

    @Test
    void rejectsAListWithAnInvalidIdBeforeLockingRows() {
        assertThatThrownBy(() -> service.lockFiles(Arrays.asList(1L, null)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("File and reference IDs must be positive");
        verifyNoInteractions(files, references, entityManager);
    }
}
