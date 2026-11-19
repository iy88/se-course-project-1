package io.github.iy88.project1.storage.persistence;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.Set;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "file_record")
class FileRecord {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "file_id")
    private Long id;
    private long ownerAccountId;
    private String purpose;
    private String state;
    private String bucket;
    private String objectKey;
    private long declaredSize;
    private String declaredContentType;
    private String targetType;
    private Long targetId;
    private String uploadRuleVersion;
    @JdbcTypeCode(SqlTypes.JSON)
    private RuleLimits uploadRules;
    private String signingCredentialRef;
    private Instant createdAt;
    private Instant uploadExpiresAt;
    private Instant cleanupAfter;
    private Instant verifiedAt;
    private String contentEtag;
    private Long verifiedSize;
    private String verifiedContentType;
    private Instant lastCleanupAt;
    private String lastCleanupRequestId;

    protected FileRecord() {}

    FileRecord(UploadRegistration upload) {
        ownerAccountId = upload.ownerAccountId();
        purpose = upload.purpose().value();
        state = "uploading";
        bucket = upload.location().bucket();
        objectKey = upload.location().key();
        declaredSize = upload.declaredSize();
        declaredContentType = upload.declaredContentType();
        if (upload.target() != null) {
            targetType = upload.target().type();
            targetId = upload.target().id();
        }
        uploadRuleVersion = upload.rules().version();
        uploadRules = new RuleLimits(upload.rules().maxBytes(), upload.rules().allowedContentTypes());
        signingCredentialRef = upload.signingCredentialRef();
        createdAt = upload.createdAt();
        uploadExpiresAt = upload.expiresAt();
        cleanupAfter = upload.cleanupAfter();
    }

    void markVerified(String etag, VerifiedContent content, Instant checkedAt) {
        if ("verified".equals(state)) {
            if (!contentEtag.equals(etag) || !verifiedContentType.equals(content.contentType())
                    || verifiedSize != content.sizeBytes()) {
                throw new FileRegistry.Rejected("FILE_CONTENT_CHANGED");
            }
            return;
        }
        if (!"uploading".equals(state)) {
            throw new FileRegistry.Rejected("FILE_NOT_REFERENCEABLE");
        }
        if (!checkedAt.isBefore(uploadExpiresAt)) {
            throw new FileRegistry.Rejected("UPLOAD_AUTH_EXPIRED");
        }
        if (declaredSize != content.sizeBytes() || !declaredContentType.equals(content.contentType())
                || etag == null || etag.isBlank()) {
            throw new FileRegistry.Rejected("FILE_CONTENT_INVALID");
        }
        state = "verified";
        verifiedAt = checkedAt;
        contentEtag = etag;
        verifiedSize = content.sizeBytes();
        verifiedContentType = content.contentType();
    }

    boolean cleanupDue(Instant now, Instant retryBefore) {
        return !cleanupAfter.isAfter(now) && uploadExpiresAt.isBefore(now)
                && (lastCleanupAt == null || !lastCleanupAt.isAfter(retryBefore));
    }

    Location claimCleanup(Instant attempt) {
        if (!"deleted".equals(state)) {
            state = "cleaning";
        }
        lastCleanupAt = attempt;
        lastCleanupRequestId = null;
        return new Location(bucket, objectKey);
    }

    void finishCleanup(Instant attempt, boolean deleted, String requestId) {
        if (attempt.equals(lastCleanupAt)) {
            lastCleanupRequestId = requestId;
            if (deleted) {
                state = "deleted";
            }
        }
    }

    FileRegistry.Entry snapshot() {
        var target = targetId == null ? null : new UploadRegistration.Target(targetType, targetId);
        var rules = new UploadRegistration.Rules(uploadRuleVersion, uploadRules.maxBytes(),
                uploadRules.allowedContentTypes());
        var upload = new UploadRegistration(ownerAccountId, FilePurpose.fromValue(purpose), target,
                new Location(bucket, objectKey), declaredSize, declaredContentType, rules,
                signingCredentialRef, createdAt, uploadExpiresAt, cleanupAfter);
        var content = verifiedSize == null ? null : new VerifiedContent(verifiedSize, verifiedContentType);
        return new FileRegistry.Entry(id, state, upload, verifiedAt, contentEtag, content);
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    private record RuleLimits(long maxBytes, Set<String> allowedContentTypes) {}
}
