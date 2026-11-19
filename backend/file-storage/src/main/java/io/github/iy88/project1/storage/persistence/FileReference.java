package io.github.iy88.project1.storage.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "file_reference")
class FileReference {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "reference_id")
    private Long id;
    private long fileId;
    private String targetType;
    private long targetId;
    private String slot;
    private String createdBy;
    private Instant createdAt;

    protected FileReference() {}

    FileReference(long fileId, UploadRegistration.Target target, String slot, String actor, Instant createdAt) {
        this.fileId = fileId;
        targetType = target.type();
        targetId = target.id();
        this.slot = slot;
        createdBy = actor;
        this.createdAt = createdAt;
    }

    long id() { return id; }
    long fileId() { return fileId; }

    FileReferences.Reference snapshot() {
        return new FileReferences.Reference(id, fileId, new UploadRegistration.Target(targetType, targetId),
                slot, createdBy, createdAt);
    }
}
