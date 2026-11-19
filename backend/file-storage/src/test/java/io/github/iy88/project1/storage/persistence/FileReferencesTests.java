package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import io.github.iy88.project1.storage.persistence.UploadRegistration.Target;
import jakarta.persistence.EntityManager;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class FileReferencesTests {
    private static final Target PRODUCT = new Target("product", 2);
    private static final Target EVIDENCE = new Target("case", 3);
    private static final Instant CREATED = Instant.parse("2026-01-01T00:00:00Z");
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

    @Test
    void attachRejectsAnotherOwnerAnUnverifiedFileAndAMismatchedPurpose() {
        var record = new FileRecord(new UploadRegistration(1, FilePurpose.PRODUCT_IMAGE, null,
                new Location("reference-fixture", "dev/product_image/file"), 64, "image/png",
                new UploadRegistration.Rules("test", 128, Set.of("image/png")), "test",
                CREATED, CREATED.plusSeconds(60), CREATED.plusSeconds(120)));
        ReflectionTestUtils.setField(record, "id", 4L);
        when(files.lockById(4L)).thenReturn(Optional.of(record));
        when(files.findById(4L)).thenReturn(Optional.of(record));

        assertThatThrownBy(() -> service.attach(2, PRODUCT, FilePurpose.PRODUCT_IMAGE, List.of(4L), "cover"))
                .isInstanceOf(FileRegistry.Rejected.class).hasMessage("RESOURCE_NOT_VISIBLE");
        assertThatThrownBy(() -> service.attach(1, PRODUCT, FilePurpose.PRODUCT_IMAGE, List.of(4L), "cover"))
                .isInstanceOf(FileRegistry.Rejected.class).hasMessage("FILE_NOT_REFERENCEABLE");

        record.markVerified("\"etag\"", new VerifiedContent(64, "image/png"), CREATED.plusSeconds(1));
        assertThatThrownBy(() -> service.attach(1, EVIDENCE, FilePurpose.CASE_EVIDENCE, List.of(4L), "evidence"))
                .isInstanceOf(FileRegistry.Rejected.class).hasMessage("FILE_PURPOSE_MISMATCH");
        verifyNoInteractions(references);
    }

    @Test
    void releasesOnlyAfterTheRequiredEvidenceReferenceExists() {
        var reference = new FileReference(4L, PRODUCT, "cover", "1", CREATED);
        ReflectionTestUtils.setField(reference, "id", 9L);
        var ids = List.of(9L);
        var basis = new FileReferences.RetentionBasis("remove_cover", Set.of("test-rule"), EVIDENCE, Set.of(EVIDENCE));
        when(files.lockById(4L)).thenReturn(Optional.of(new FileRecord()));
        when(references.findByTargetTypeAndTargetIdAndIdInOrderById(PRODUCT.type(), PRODUCT.id(), ids))
                .thenReturn(List.of(reference));
        when(references.lockByTargetAndIds(PRODUCT.type(), PRODUCT.id(), ids)).thenReturn(List.of(reference));

        assertThatThrownBy(() -> service.release(PRODUCT, ids, basis))
                .isInstanceOf(FileRegistry.Rejected.class).hasMessage("FILE_RETENTION_REQUIRED");
        verify(references, never()).delete(any());

        when(references.existsByFileIdAndTargetTypeAndTargetId(4L, EVIDENCE.type(), EVIDENCE.id())).thenReturn(true);
        assertThat(service.release(PRODUCT, ids, basis))
                .isEqualTo(new FileReferences.Released(PRODUCT, ids, List.of(4L)));
        verify(references).delete(reference);
    }
}
