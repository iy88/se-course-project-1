package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import jakarta.persistence.EntityManager;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Persistence API for use by authorized file workflows. */
@Service
@Profile("infrastructure")
@EnableConfigurationProperties(FileRulesProperties.class)
public class FileRegistry {
    private final FileRecordRepository repository;
    private final FileRulesProperties rules;
    private final EntityManager entityManager;

    FileRegistry(FileRecordRepository repository, FileRulesProperties rules, EntityManager entityManager) {
        this.repository = repository;
        this.rules = rules;
        this.entityManager = entityManager;
    }

    @Transactional
    public Entry register(UploadRegistration.Draft draft) {
        var upload = draft.withRules(rules.rulesFor(draft.purpose()));
        return repository.save(new FileRecord(upload)).snapshot();
    }

    @Transactional(readOnly = true)
    public Entry getOwned(long fileId, long accountId) {
        return repository.findByIdAndOwnerAccountId(fileId, accountId)
                .orElseThrow(() -> new Rejected("RESOURCE_NOT_VISIBLE")).snapshot();
    }

    @Transactional
    public Entry markVerified(long fileId, long accountId, String etag, VerifiedContent content) {
        var record = repository.lockOwned(fileId, accountId)
                .orElseThrow(() -> new Rejected("RESOURCE_NOT_VISIBLE"));
        entityManager.refresh(record);
        record.markVerified(etag, content, Instant.now().truncatedTo(ChronoUnit.MICROS));
        return record.snapshot();
    }

    public record Entry(long fileId, String state, UploadRegistration upload, Instant verifiedAt,
                        String etag, VerifiedContent content) {}

    public static final class Rejected extends RuntimeException {
        public Rejected(String code) {
            super(code);
        }
    }
}
