package io.github.iy88.project1.storage.persistence;

import jakarta.persistence.LockModeType;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;
import org.springframework.data.repository.query.Param;

interface FileRecordRepository extends Repository<FileRecord, Long> {
    FileRecord save(FileRecord record);

    Optional<FileRecord> findById(long id);

    @Query("""
            select f from FileRecord f
            where f.id = :id and exists (select r.id from FileReference r
                where r.fileId = f.id and r.targetType = :type and r.targetId = :targetId)
            """)
    Optional<FileRecord> findReferenced(long id, String type, long targetId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select f from FileRecord f where f.id = :id")
    Optional<FileRecord> lockById(long id);

    @Query("""
            select f.id from FileRecord f
            where f.bucket = :bucket
              and (locate(:images, f.objectKey) = 1 or locate(:evidence, f.objectKey) = 1)
              and f.cleanupAfter <= :now and f.uploadExpiresAt < :now
              and (f.lastCleanupAt is null or f.lastCleanupAt <= :retryBefore)
              and not exists (select r.id from FileReference r where r.fileId = f.id)
            order by f.lastCleanupAt asc nulls first, f.id
            """)
    List<Long> cleanupCandidates(String bucket, String images, String evidence, Instant now, Instant retryBefore,
                                 Pageable page);

    Optional<FileRecord> findByIdAndOwnerAccountId(long id, long ownerAccountId);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select f from FileRecord f where f.id = :id and f.ownerAccountId = :owner")
    Optional<FileRecord> lockOwned(@Param("id") long id, @Param("owner") long ownerAccountId);
}
