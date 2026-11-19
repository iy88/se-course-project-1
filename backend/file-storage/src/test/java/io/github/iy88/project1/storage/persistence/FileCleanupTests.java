package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.PageRequest;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FileCleanupTests {
    private static final String BUCKET = "cleanup-fixture";
    private static final Instant CREATED = Instant.parse("2026-01-01T00:00:00Z");

    private final FileRecordRepository files = mock(FileRecordRepository.class);
    private final FileReferenceRepository references = mock(FileReferenceRepository.class);
    private final PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
    private final OssFileObjects objects = mock(OssFileObjects.class);
    private final FileCleanup cleanup = new FileCleanup(files, references, rules(), new TransactionTemplate(manager));

    @BeforeEach
    void prepareBatch() {
        when(manager.getTransaction(any())).thenAnswer(invocation -> new SimpleTransactionStatus());
        when(objects.bucket()).thenReturn(BUCKET);
        when(objects.purposePrefix(FilePurpose.PRODUCT_IMAGE)).thenReturn("dev/product_image/");
        when(objects.purposePrefix(FilePurpose.CASE_EVIDENCE)).thenReturn("dev/case_evidence/");
    }

    @Test
    void rechecksEligibilityAndCommitsTheClaimBeforeDeleting() {
        var deletable = file(1, CREATED);
        var referenced = file(2, CREATED);
        var notDue = file(3, Instant.now());
        candidates(deletable, referenced, notDue);
        when(references.existsByFileId(2)).thenReturn(true);
        when(objects.delete(location(1))).thenAnswer(invocation -> {
            assertThat(deletable.snapshot().state()).isEqualTo("cleaning");
            return "deleted-request";
        });

        assertThat(cleanup.runBatch(objects, 8)).isEqualTo(new FileCleanup.Result(1, List.of()));

        var calls = inOrder(objects, files, manager);
        calls.verify(objects).requireWritableBucket();
        calls.verify(files).cleanupCandidates(eq(BUCKET), eq("dev/product_image/"), eq("dev/case_evidence/"),
                any(Instant.class), any(Instant.class), eq(PageRequest.of(0, 8)));
        calls.verify(files).lockById(1);
        calls.verify(manager).commit(any());
        calls.verify(objects).delete(location(1));
        calls.verify(files).lockById(1);
        calls.verify(manager).commit(any());
        verify(objects, never()).delete(location(2));
        verify(objects, never()).delete(location(3));
        assertThat(deletable.snapshot().state()).isEqualTo("deleted");
        assertThat(deletable.snapshot().lastCleanupRequestId()).isEqualTo("deleted-request");
        assertThat(referenced.snapshot().state()).isEqualTo("uploading");
        assertThat(notDue.snapshot().state()).isEqualTo("uploading");
    }

    @Test
    void recordsAnOssFailureContinuesTheBatchAndWaitsBeforeRetrying() {
        var failed = file(1, CREATED);
        var next = file(2, CREATED);
        candidates(failed, next);
        var failure = mock(OssFileObjects.Failure.class);
        when(failure.reason()).thenReturn(OssFileObjects.Reason.UNAVAILABLE);
        when(failure.requestId()).thenReturn("failed-request");
        when(objects.delete(location(1))).thenThrow(failure);
        when(objects.delete(location(2))).thenReturn("next-request");

        var result = cleanup.runBatch(objects, 8);

        assertThat(result.deleted()).isEqualTo(1);
        assertThat(result.failures()).containsExactly(
                new FileCleanup.FailedAttempt(1, OssFileObjects.Reason.UNAVAILABLE, "failed-request"));
        assertThat(failed.snapshot().state()).isEqualTo("cleaning");
        assertThat(failed.snapshot().lastCleanupRequestId()).isEqualTo("failed-request");
        assertThat(next.snapshot().state()).isEqualTo("deleted");

        candidates(failed);
        assertThat(cleanup.runBatch(objects, 8)).isEqualTo(new FileCleanup.Result(0, List.of()));
        verify(objects).delete(location(1));
    }

    @Test
    void ignoresCompletionOfAnOlderCleanupAttempt() {
        var record = file(1, CREATED);
        Instant first = CREATED.plusSeconds(180);
        Instant second = first.plusSeconds(60);
        record.claimCleanup(first);
        record.claimCleanup(second);

        record.finishCleanup(first, true, "stale-request");

        assertThat(record.snapshot().state()).isEqualTo("cleaning");
        assertThat(record.snapshot().lastCleanupRequestId()).isNull();
        record.finishCleanup(second, true, "current-request");
        assertThat(record.snapshot().state()).isEqualTo("deleted");
    }

    private void candidates(FileRecord... records) {
        var ids = java.util.Arrays.stream(records).map(record -> record.snapshot().fileId()).toList();
        when(files.cleanupCandidates(eq(BUCKET), eq("dev/product_image/"), eq("dev/case_evidence/"),
                any(Instant.class), any(Instant.class), eq(PageRequest.of(0, 8)))).thenReturn(ids);
        for (var record : records) {
            when(files.lockById(record.snapshot().fileId())).thenReturn(Optional.of(record));
        }
    }

    private static FileRecord file(long id, Instant created) {
        var record = new FileRecord(new UploadRegistration(1, FilePurpose.PRODUCT_IMAGE, null, location(id),
                64, "image/png", new UploadRegistration.Rules("test", 128, Set.of("image/png")), "test",
                created, created.plusSeconds(60), created.plusSeconds(120)));
        ReflectionTestUtils.setField(record, "id", id);
        return record;
    }

    private static Location location(long id) {
        return new Location(BUCKET, "dev/product_image/" + id);
    }

    private static FileRulesProperties rules() {
        var limits = new FileRulesProperties.Limits(128, Set.of("image/png"));
        return new FileRulesProperties("test", limits, limits, 60, 3600, 60, 120);
    }
}
