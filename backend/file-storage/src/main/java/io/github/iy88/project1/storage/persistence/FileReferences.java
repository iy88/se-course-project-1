package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.persistence.FileRegistry.Rejected;
import io.github.iy88.project1.storage.persistence.UploadRegistration.Target;
import jakarta.persistence.EntityManager;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** Internal file operations. Callers authorize the actor and subject before entering the file lock domain. */
@Service
@Profile("infrastructure")
@Transactional(propagation = Propagation.MANDATORY)
public class FileReferences {
    private final FileRecordRepository files;
    private final FileReferenceRepository references;
    private final EntityManager entityManager;

    FileReferences(FileRecordRepository files, FileReferenceRepository references, EntityManager entityManager) {
        this.files = files;
        this.references = references;
        this.entityManager = entityManager;
    }

    /** Prelock the union when several file operations share one subject transaction. */
    public void lockFiles(Collection<Long> fileIds) {
        orderedIds(fileIds).forEach(id -> lockFile(Objects.requireNonNull(id)));
    }

    public List<Reference> attach(long accountId, Target target, FilePurpose purpose,
                                  Collection<Long> fileIds, String slot) {
        requireText(slot);
        if (accountId <= 0 || purpose == null || target == null) {
            throw new IllegalArgumentException("Missing file attachment input");
        }
        var ids = orderedIds(fileIds);
        lockFiles(ids);
        return ids.stream().map(fileId -> {
            var entry = files.findById(fileId).orElseThrow().snapshot();
            if (entry.upload().ownerAccountId() != accountId) {
                throw new Rejected("RESOURCE_NOT_VISIBLE");
            }
            return add(entry, target, purpose, slot, Long.toString(accountId));
        }).toList();
    }

    /** The subject authorizes reading and copying the source and writing the destination. */
    public List<Reference> retain(String actor, Target source, Target target, FilePurpose purpose,
                                  Collection<Long> fileIds, String slot) {
        requireText(slot);
        requireText(actor);
        if (source == null || target == null || purpose == null) {
            throw new IllegalArgumentException("Missing file retention input");
        }
        var ids = orderedIds(fileIds);
        lockFiles(ids);
        return ids.stream().map(fileId -> {
            var entry = files.findById(fileId).orElseThrow().snapshot();
            requireReference(source, fileId);
            return add(entry, target, purpose, slot, actor);
        }).toList();
    }

    @Transactional(readOnly = true)
    public List<Reference> current(Target target, String slot) {
        requireText(slot);
        return references.findByTargetTypeAndTargetIdAndSlotOrderById(target.type(), target.id(), slot)
                .stream().map(FileReference::snapshot).toList();
    }

    /** Return the first reference per target in one query, ordered by target and reference ID. */
    @Transactional(readOnly = true)
    public Map<Long, Reference> firstCurrent(String targetType, Collection<Long> targetIds, String slot) {
        requireText(targetType);
        requireText(slot);
        var ids = orderedIds(targetIds);
        if (ids.isEmpty()) {
            return Map.of();
        }
        Map<Long, Reference> firstByTarget = new LinkedHashMap<>();
        for (FileReference reference : references
                .findByTargetTypeAndTargetIdInAndSlotOrderByTargetIdAscIdAsc(targetType, ids, slot)) {
            Reference snapshot = reference.snapshot();
            firstByTarget.putIfAbsent(snapshot.target().id(), snapshot);
        }
        return firstByTarget;
    }

    @Transactional(readOnly = true)
    public List<Long> prepareRelease(Target target, Collection<Long> referenceIds) {
        var ids = orderedIds(referenceIds);
        if (ids.isEmpty()) {
            return List.of();
        }
        var matches = references.findByTargetTypeAndTargetIdAndIdInOrderById(target.type(), target.id(), ids);
        requireAll(ids, matches);
        return orderedIds(matches.stream().map(reference -> Objects.requireNonNull(reference).fileId()).toList());
    }

    public Released release(Target target, Collection<Long> referenceIds, RetentionBasis basis) {
        var ids = orderedIds(referenceIds);
        if (ids.isEmpty()) {
            return new Released(target, ids, List.of());
        }
        var fileIds = prepareRelease(target, ids);
        lockFiles(fileIds);
        var matches = references.lockByTargetAndIds(target.type(), target.id(), ids);
        requireAll(ids, matches);
        for (long fileId : fileIds) {
            for (Target preserved : basis.preservedTargets()) {
                if (target.equals(preserved)
                        || !references.existsByFileIdAndTargetTypeAndTargetId(fileId, preserved.type(), preserved.id())) {
                    throw new Rejected("FILE_RETENTION_REQUIRED");
                }
            }
        }
        matches.forEach(references::delete);
        return new Released(target, ids, fileIds);
    }

    public FileRegistry.Entry readReferenced(Target target, long fileId) {
        var entry = files.findReferenced(fileId, target.type(), target.id())
                .orElseThrow(() -> new Rejected("RESOURCE_NOT_VISIBLE")).snapshot();
        requireVerified(entry);
        return entry;
    }

    private Reference add(FileRegistry.Entry entry, Target target, FilePurpose purpose, String slot, String actor) {
        requireVerified(entry);
        if (entry.upload().purpose() != purpose) {
            throw new Rejected("FILE_PURPOSE_MISMATCH");
        }
        return references.findByFileIdAndTargetTypeAndTargetIdAndSlot(entry.fileId(), target.type(), target.id(), slot)
                .orElseGet(() -> references.save(new FileReference(entry.fileId(), target, slot, actor,
                        Instant.now().truncatedTo(ChronoUnit.MICROS))))
                .snapshot();
    }

    private void lockFile(long id) {
        var file = files.lockById(id).orElseThrow(() -> new Rejected("RESOURCE_NOT_VISIBLE"));
        // A subject can have read this entity before waiting for the file lock.
        entityManager.refresh(file);
    }

    private void requireReference(Target target, long fileId) {
        if (!references.existsByFileIdAndTargetTypeAndTargetId(fileId, target.type(), target.id())) {
            throw new Rejected("RESOURCE_NOT_VISIBLE");
        }
    }

    private static void requireVerified(FileRegistry.Entry entry) {
        if (!"verified".equals(entry.state())) {
            throw new Rejected("FILE_NOT_REFERENCEABLE");
        }
    }

    private static void requireAll(List<Long> ids, List<FileReference> matches) {
        if (matches.size() != ids.size()) {
            throw new Rejected("RESOURCE_NOT_VISIBLE");
        }
    }

    private static List<Long> orderedIds(Collection<Long> ids) {
        if (ids.stream().anyMatch(id -> id == null || id <= 0)) {
            throw new IllegalArgumentException("File and reference IDs must be positive");
        }
        return ids.stream().distinct().sorted().toList();
    }

    private static void requireText(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("File actions, actors and slots must be named");
        }
    }

    public record Reference(long referenceId, long fileId, Target target, String slot, String createdBy,
                            Instant createdAt) {}

    public record RetentionBasis(String action, Set<String> ruleRefs, Target basisRef, Set<Target> preservedTargets) {
        public RetentionBasis {
            requireText(action);
            ruleRefs = Set.copyOf(ruleRefs);
            if (ruleRefs.isEmpty()) {
                throw new IllegalArgumentException("File release requires at least one rule reference");
            }
            ruleRefs.forEach(FileReferences::requireText);
            preservedTargets = Set.copyOf(preservedTargets);
        }
    }

    public record Released(Target target, List<Long> releasedReferenceIds, List<Long> affectedFileIds) {}
}
