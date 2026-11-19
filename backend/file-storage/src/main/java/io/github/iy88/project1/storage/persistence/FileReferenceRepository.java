package io.github.iy88.project1.storage.persistence;

import jakarta.persistence.LockModeType;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

interface FileReferenceRepository extends Repository<FileReference, Long> {
    FileReference save(FileReference reference);

    void delete(FileReference reference);

    boolean existsByFileId(long fileId);

    boolean existsByFileIdAndTargetTypeAndTargetId(long fileId, String targetType, long targetId);

    Optional<FileReference> findByFileIdAndTargetTypeAndTargetIdAndSlot(
            long fileId, String targetType, long targetId, String slot);

    List<FileReference> findByTargetTypeAndTargetIdAndIdInOrderById(
            String targetType, long targetId, Collection<Long> ids);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("""
            select r from FileReference r
            where r.targetType = :type and r.targetId = :targetId and r.id in :ids
            order by r.id
            """)
    List<FileReference> lockByTargetAndIds(String type, long targetId, Collection<Long> ids);
}
