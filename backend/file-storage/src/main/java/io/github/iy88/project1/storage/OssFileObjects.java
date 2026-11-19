package io.github.iy88.project1.storage;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.PresignOptions;
import com.aliyun.sdk.service.oss2.credentials.Credentials;
import com.aliyun.sdk.service.oss2.exceptions.OperationException;
import com.aliyun.sdk.service.oss2.exceptions.ServiceException;
import com.aliyun.sdk.service.oss2.models.DeleteObjectRequest;
import com.aliyun.sdk.service.oss2.models.GetObjectRequest;
import com.aliyun.sdk.service.oss2.models.HeadObjectRequest;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.time.Instant;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Supplier;
import java.util.regex.Pattern;

/** OSS operations scoped to the Bucket and object prefix of one deployment. */
public final class OssFileObjects {
    private static final String UUID_PATTERN =
            "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

    private final OSSClient client;
    private final String bucket;
    private final String prefix;
    private final Pattern managedKey;

    public OssFileObjects(OSSClient client, String bucket, String prefix) {
        this.client = Objects.requireNonNull(client);
        if (bucket == null || !bucket.matches("[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")) {
            throw new IllegalArgumentException("Invalid OSS_BUCKET");
        }
        if (prefix == null || prefix.length() > 128 || !prefix.matches("[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*")) {
            throw new IllegalArgumentException("Invalid OSS_PREFIX");
        }
        this.bucket = bucket;
        this.prefix = prefix;
        managedKey = Pattern.compile(Pattern.quote(prefix) + "/("
                + FilePurpose.PRODUCT_IMAGE.value() + "|" + FilePurpose.CASE_EVIDENCE.value()
                + ")/" + UUID_PATTERN);
    }

    public Location newLocation(FilePurpose purpose) {
        return new Location(bucket, prefix + "/" + purpose.value() + "/" + UUID.randomUUID());
    }

    public void requireWritableBucket() {
        call(() -> {
            OssClients.requirePrivateUnversionedBucket(client, bucket);
            return null;
        });
    }

    public Optional<Metadata> head(Location location) {
        requireManagedLocation(location);
        try {
            var response = call(() -> client.headObject(HeadObjectRequest.newBuilder()
                    .bucket(location.bucket()).key(location.key()).build()));
            return Optional.of(new Metadata(response.eTag(), response.contentLength(), response.contentType()));
        } catch (Failure failure) {
            if (failure.reason() == Reason.OBJECT_MISSING) {
                return Optional.empty();
            }
            throw failure;
        }
    }

    public <T> T readForVerification(Location location, Metadata expected, ContentReader<T> reader) {
        requireManagedLocation(location);
        var response = call(() -> client.getObject(GetObjectRequest.newBuilder()
                .bucket(location.bucket()).key(location.key()).ifMatch(expected.etag()).build()));
        T result;
        try (var body = response.body()) {
            var actual = new Metadata(response.eTag(), response.contentLength(), response.contentType());
            if (!expected.equals(actual)) {
                throw new Failure(Reason.CONTENT_CHANGED, response.requestId());
            }
            result = reader.read(body);
        } catch (IOException failure) {
            throw new Failure(Reason.UNAVAILABLE, response.requestId());
        }
        if (head(location).filter(expected::equals).isEmpty()) {
            throw new Failure(Reason.CONTENT_CHANGED, response.requestId());
        }
        return result;
    }

    public URI presignRead(Location location, VerifiedContent content, Instant expiresAt) {
        requireManagedLocation(location);
        var request = GetObjectRequest.newBuilder().bucket(location.bucket()).key(location.key())
                .responseCacheControl("private, no-store");
        if ("application/pdf".equals(content.contentType())) {
            request.responseContentDisposition("attachment");
        }
        var result = call(() -> client.presign(request.build(),
                PresignOptions.newBuilder().expiration(expiresAt).build()));
        URI url = URI.create(result.url());
        if (!"https".equals(url.getScheme())) {
            throw new Failure(Reason.INVALID_CONFIGURATION, null);
        }
        return url;
    }

    public UploadForm signUpload(Location location, String region, Credentials credentials,
                                 Instant signedAt, Instant expiresAt, long sizeBytes, String contentType) {
        requireManagedLocation(location);
        requireWritableBucket();
        return OssPostPolicy.sign(location, region, credentials, signedAt, expiresAt, sizeBytes, contentType);
    }

    public String delete(Location location) {
        requireManagedLocation(location);
        try {
            return call(() -> client.deleteObject(DeleteObjectRequest.newBuilder()
                    .bucket(location.bucket()).key(location.key()).build())).requestId();
        } catch (Failure failure) {
            if (failure.reason() != Reason.OBJECT_MISSING) {
                throw failure;
            }
            return failure.requestId();
        }
    }

    private void requireManagedLocation(Location location) {
        if (!bucket.equals(location.bucket()) || !managedKey.matcher(location.key()).matches()) {
            throw new Failure(Reason.INVALID_CONFIGURATION, null);
        }
    }

    private static <T> T call(Supplier<T> operation) {
        try {
            return operation.get();
        } catch (OssClients.InvalidBucketException failure) {
            throw new Failure(Reason.INVALID_CONFIGURATION, null);
        } catch (OperationException | ServiceException failure) {
            var service = ServiceException.asCause(failure);
            if (service == null && failure instanceof ServiceException direct) {
                service = direct;
            }
            if (service == null) {
                throw new Failure(Reason.UNAVAILABLE, null);
            }
            Reason reason = switch (Objects.toString(service.errorCode(), "")) {
                case "NoSuchKey" -> Reason.OBJECT_MISSING;
                case "PreconditionFailed" -> Reason.CONTENT_CHANGED;
                default -> Reason.UNAVAILABLE;
            };
            throw new Failure(reason, service.requestId());
        }
    }

    public record Location(String bucket, String key) {}

    public record Metadata(String etag, Long sizeBytes, String contentType) {}

    public record UploadForm(URI url, Map<String, String> fields) {
        @Override
        public String toString() {
            return "OSS upload form";
        }
    }

    @FunctionalInterface
    public interface ContentReader<T> {
        T read(InputStream content) throws IOException;
    }

    public enum Reason {
        OBJECT_MISSING, CONTENT_CHANGED, INVALID_CONFIGURATION, UNAVAILABLE
    }

    public static final class Failure extends RuntimeException {
        private final Reason reason;
        private final String requestId;

        private Failure(Reason reason, String requestId) {
            super(reason.name());
            this.reason = reason;
            this.requestId = requestId;
        }

        public Reason reason() {
            return reason;
        }

        public String requestId() {
            return requestId;
        }
    }
}
