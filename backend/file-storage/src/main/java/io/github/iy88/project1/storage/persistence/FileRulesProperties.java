package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.content.FileContentVerifier;
import java.util.Objects;
import java.util.Set;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.files")
public record FileRulesProperties(String ruleVersion, Limits productImage, Limits caseEvidence,
                                  int readUrlTtlSeconds, int cleanupScanSeconds,
                                  int uploadTtlSeconds, int tempRetentionSeconds) {
    public FileRulesProperties {
        if (ruleVersion == null || ruleVersion.isBlank()) {
            throw new IllegalArgumentException("FILE_RULE_VERSION is required");
        }
        if (readUrlTtlSeconds < 1 || readUrlTtlSeconds > 300
                || cleanupScanSeconds < 1 || cleanupScanSeconds > 3600) {
            throw new IllegalArgumentException("File read TTL must be 1–300 s and cleanup scan 1–3600 s");
        }
        if (uploadTtlSeconds < 1 || uploadTtlSeconds > 3600 || tempRetentionSeconds <= uploadTtlSeconds) {
            throw new IllegalArgumentException("FILE_UPLOAD_TTL_SECONDS must be 1–3600 and less than FILE_TEMP_RETENTION_SECONDS");
        }
        Objects.requireNonNull(productImage, "Product image limits are required");
        Objects.requireNonNull(caseEvidence, "Case evidence limits are required");
        if (!productImage.allowedContentTypes().stream().allMatch(FileContentVerifier::isImage)) {
            throw new IllegalArgumentException("Product image formats must be JPEG or PNG");
        }
    }

    public UploadRegistration.Rules rulesFor(FilePurpose purpose) {
        var limits = switch (purpose) {
            case PRODUCT_IMAGE -> productImage;
            case CASE_EVIDENCE -> caseEvidence;
        };
        return new UploadRegistration.Rules(ruleVersion, limits.maxBytes(), limits.allowedContentTypes());
    }

    public record Limits(long maxBytes, Set<String> allowedContentTypes) {
        public Limits {
            if (maxBytes <= 0 || allowedContentTypes == null || allowedContentTypes.isEmpty()
                    || !allowedContentTypes.stream().allMatch(FileContentVerifier::supports)) {
                throw new IllegalArgumentException("File limits need a positive byte limit and supported MIME types");
            }
            allowedContentTypes = Set.copyOf(allowedContentTypes);
        }
    }
}
