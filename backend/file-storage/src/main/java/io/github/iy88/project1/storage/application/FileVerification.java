package io.github.iy88.project1.storage.application;

import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.content.FileContentVerifier;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import java.time.Instant;
import java.util.function.Consumer;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/** Verifies uploaded files after the owning subject authorizes the operation. */
@Service
@Profile("infrastructure")
public class FileVerification {
    private final FileRegistry registry;
    private final TransactionTemplate transaction;

    public FileVerification(FileRegistry registry, TransactionTemplate transaction) {
        this.registry = registry;
        this.transaction = transaction;
    }

    /**
     * The caller supplies the subject's access check. During the write transaction it must
     * acquire and recheck account and subject facts before the registry takes the file lock.
     */
    @Transactional(propagation = Propagation.NEVER)
    public FileRegistry.Entry verify(long fileId, long accountId, OssFileObjects objects,
                                     Consumer<FileRegistry.Entry> requireAccess) {
        var current = registry.getOwned(fileId, accountId);
        requireAccess.accept(current);
        if ("verified".equals(current.state())) {
            return current;
        }
        if (!"uploading".equals(current.state())) {
            throw new FileRegistry.Rejected("FILE_NOT_REFERENCEABLE");
        }
        var upload = current.upload();
        if (!Instant.now().isBefore(upload.expiresAt())) {
            throw new FileRegistry.Rejected("UPLOAD_AUTH_EXPIRED");
        }
        objects.requireWritableBucket();
        var head = objects.head(upload.location())
                .orElseThrow(() -> new FileRegistry.Rejected("FILE_UPLOAD_INCOMPLETE"));
        if (head.sizeBytes() == null || head.sizeBytes() != upload.declaredSize()
                || !upload.declaredContentType().equals(head.contentType())) {
            throw new FileRegistry.Rejected("FILE_CONTENT_INVALID");
        }
        var content = objects.readForVerification(upload.location(), head,
                body -> FileContentVerifier.verify(body, upload.declaredSize(), upload.declaredContentType(),
                        upload.rules().maxBytes()));

        return transaction.execute(status -> {
            requireAccess.accept(registry.getOwned(fileId, accountId));
            return registry.markVerified(fileId, accountId, head.etag(), content);
        });
    }
}
