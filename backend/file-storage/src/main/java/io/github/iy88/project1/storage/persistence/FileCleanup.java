package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/** One bounded cleanup pass for the configured private bucket. */
@Service
@Profile("infrastructure")
public class FileCleanup {
    private final FileRecordRepository files;
    private final FileReferenceRepository references;
    private final FileRulesProperties rules;
    private final TransactionTemplate transaction;

    FileCleanup(FileRecordRepository files, FileReferenceRepository references, FileRulesProperties rules,
                TransactionTemplate transaction) {
        this.files = files;
        this.references = references;
        this.rules = rules;
        this.transaction = transaction;
    }

    @Transactional(propagation = Propagation.NEVER)
    public Result runBatch(OssFileObjects objects, int batchSize) {
        objects.requireWritableBucket();
        var now = Instant.now().truncatedTo(ChronoUnit.MICROS);
        var retryBefore = now.minusSeconds(rules.cleanupScanSeconds());
        var ids = files.cleanupCandidates(now, retryBefore, PageRequest.of(0, batchSize));
        var failed = new ArrayList<FailedAttempt>();
        int deleted = 0;
        for (long id : ids) {
            var location = transaction.execute(status -> claim(id, now, retryBefore));
            if (location == null) {
                continue;
            }
            String requestId;
            try {
                requestId = objects.delete(location);
            } catch (OssFileObjects.Failure failure) {
                finish(id, now, false, failure.requestId());
                failed.add(new FailedAttempt(id, failure.reason(), failure.requestId()));
                continue;
            }
            finish(id, now, true, requestId);
            deleted++;
        }
        return new Result(deleted, List.copyOf(failed));
    }

    private Location claim(long id, Instant attempt, Instant retryBefore) {
        var file = files.lockById(id).orElseThrow();
        if (!file.cleanupDue(attempt, retryBefore) || references.existsByFileId(id)) {
            return null;
        }
        return file.claimCleanup(attempt);
    }

    private void finish(long id, Instant attempt, boolean deleted, String requestId) {
        transaction.executeWithoutResult(status ->
                files.lockById(id).orElseThrow().finishCleanup(attempt, deleted, requestId));
    }

    public record Result(int deleted, List<FailedAttempt> failures) {}

    public record FailedAttempt(long fileId, OssFileObjects.Reason reason, String requestId) {}
}
