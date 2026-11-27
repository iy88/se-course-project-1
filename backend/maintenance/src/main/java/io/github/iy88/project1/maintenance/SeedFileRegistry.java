package io.github.iy88.project1.maintenance;

import java.sql.SQLException;
import java.time.Instant;

/** Writes the real file_record/file_reference rows required by product and case reads. */
final class SeedFileRegistry {
    private SeedFileRegistry() {
    }

    static long record(SeedDatabase database, SeedFiles.UploadedFile file, long ownerId,
                       String bucket, String ruleVersion, Instant now) throws SQLException {
        Instant createdAt = now.minusSeconds(120);
        Instant verifiedAt = now.minusSeconds(60);
        Instant uploadExpiresAt = now.plusSeconds(3_600);
        Instant cleanupAfter = now.plusSeconds(7 * 86_400L);
        return database.insert("""
                insert into file_record (owner_account_id, purpose, state, bucket, object_key,
                    declared_size, declared_content_type, upload_rule_version, upload_rules,
                    signing_credential_ref, created_at, upload_expires_at, cleanup_after,
                    verified_at, content_etag, verified_size, verified_content_type)
                values (?, ?, 'verified', ?, ?, ?, ?, ?, ?::jsonb, 'maintenance:seed',
                    ?, ?, ?, ?, ?, ?, ?)
                returning file_id
                """, ownerId, file.purpose(), bucket, file.objectKey(), (long) file.sizeBytes(), file.asset().contentType(), ruleVersion,
                "{\"version\":" + SeedSupport.jsonString(ruleVersion)
                        + ",\"maxBytes\":104857600,\"allowedContentTypes\":[\"image/jpeg\",\"image/png\"]}",
                createdAt, uploadExpiresAt, cleanupAfter, verifiedAt, file.eTag(),
                (long) file.sizeBytes(), file.asset().contentType());
    }

    static long attach(SeedDatabase database, long fileId, String targetType, long targetId,
                       String slot, String createdBy, Instant now) throws SQLException {
        return database.insert("""
                insert into file_reference (file_id, target_type, target_id, slot, created_by, created_at)
                values (?, ?, ?, ?, ?, ?)
                returning reference_id
                """, fileId, targetType, targetId, slot, createdBy, now);
    }
}
