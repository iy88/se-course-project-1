package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import java.time.Instant;
import java.util.Objects;
import java.util.Set;

/** Internal, server-established registration of an authorized upload. */
public record UploadRegistration(
        long ownerAccountId, FilePurpose purpose, Target target, Location location,
        long declaredSize, String declaredContentType, Rules rules,
        String signingCredentialRef, Instant createdAt, Instant expiresAt, Instant cleanupAfter) {

    public UploadRegistration {
        Objects.requireNonNull(purpose);
        Objects.requireNonNull(location);
        Objects.requireNonNull(rules);
        if (ownerAccountId <= 0 || declaredSize <= 0 || declaredSize > rules.maxBytes()
                || declaredContentType == null || !rules.allowedContentTypes().contains(declaredContentType)
                || signingCredentialRef == null || signingCredentialRef.isBlank()
                || !createdAt.isBefore(expiresAt) || !expiresAt.isBefore(cleanupAfter)) {
            throw new IllegalArgumentException("Invalid upload registration");
        }
    }

    public record Target(String type, long id) {
        public Target {
            if (type == null || type.isBlank() || id <= 0) {
                throw new IllegalArgumentException("Invalid file resource reference");
            }
        }
    }

    public record Draft(long ownerAccountId, FilePurpose purpose, Target target, Location location,
                        long declaredSize, String declaredContentType, String signingCredentialRef,
                        Instant createdAt, Instant expiresAt, Instant cleanupAfter) {
        public Draft {
            if ("image/jpg".equals(declaredContentType)) {
                declaredContentType = "image/jpeg";
            }
        }

        public UploadRegistration withRules(Rules rules) {
            return new UploadRegistration(ownerAccountId, purpose, target, location, declaredSize,
                    declaredContentType, rules, signingCredentialRef, createdAt, expiresAt, cleanupAfter);
        }
    }

    public record Rules(String version, long maxBytes, Set<String> allowedContentTypes) {
        public Rules {
            allowedContentTypes = Set.copyOf(allowedContentTypes);
            if (version == null || version.isBlank() || maxBytes <= 0 || allowedContentTypes.isEmpty()) {
                throw new IllegalArgumentException("Invalid file rules snapshot");
            }
        }
    }
}
