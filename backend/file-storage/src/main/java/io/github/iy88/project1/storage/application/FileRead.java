package io.github.iy88.project1.storage.application;

import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.FileRulesProperties;
import io.github.iy88.project1.storage.persistence.UploadRegistration.Target;
import java.net.URI;
import java.time.Instant;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/** Prepares a short-lived read URL after the subject authorizes access to the reference. */
@Service
@Profile("infrastructure")
public class FileRead {
    private final FileReferences references;
    private final FileRulesProperties rules;
    private final TransactionTemplate transaction;

    FileRead(FileReferences references, FileRulesProperties rules, TransactionTemplate transaction) {
        this.references = references;
        this.rules = rules;
        this.transaction = transaction;
    }

    @Transactional(propagation = Propagation.NEVER)
    public AuthorizedRead prepare(Target target, long fileId, OssFileObjects objects, Runnable requireAccess) {
        var entry = transaction.execute(status -> {
            requireAccess.run();
            return references.readReferenced(target, fileId);
        });
        return sign(fileId, objects, entry);
    }

    /** Signs a reference already authorized by the caller within its consistent read snapshot. */
    @Transactional(propagation = Propagation.MANDATORY, readOnly = true)
    public AuthorizedRead signInReadSnapshot(Target target, long fileId, OssFileObjects objects) {
        return sign(fileId, objects, references.readReferenced(target, fileId));
    }

    private AuthorizedRead sign(long fileId, OssFileObjects objects,
                                FileRegistry.Entry entry) {
        if (entry == null) {
            throw new IllegalStateException("File read transaction returned no result");
        }
        var expiresAt = Instant.now().plusSeconds(rules.readUrlTtlSeconds());
        var content = entry.content();
        var url = objects.presignRead(entry.upload().location(), content, expiresAt);
        return new AuthorizedRead(fileId, url, expiresAt, content.contentType(), content.sizeBytes());
    }

    public record AuthorizedRead(long fileId, URI url, Instant expiresAt, String contentType, long sizeBytes) {
        @Override
        public String toString() {
            return "Authorized file read " + fileId;
        }
    }
}
