package io.github.iy88.project1.storage;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.credentials.StaticCredentialsProvider;
import com.aliyun.sdk.service.oss2.exceptions.OperationException;
import com.aliyun.sdk.service.oss2.exceptions.ServiceException;
import com.aliyun.sdk.service.oss2.models.GetBucketAclRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketVersioningRequest;
import com.aliyun.sdk.service.oss2.retry.NopRetryer;
import java.io.Serial;
import java.time.Duration;
import java.util.function.Function;

public final class OssClients {

    private OssClients() {
    }

    public static <T> T use(String endpoint, String region, String accessKey, String secret,
                            Function<OSSClient, T> action) {
        try (var session = new ClientSession(open(endpoint, region, accessKey, secret))) {
            return action.apply(session.client());
        } catch (OperationException failure) {
            if (failure.getCause() instanceof ServiceException serviceFailure) {
                throw serviceError(serviceFailure);
            }
            throw new IllegalStateException("OSS request failed (" + failure.getClass().getSimpleName() + ")");
        } catch (ServiceException failure) {
            throw serviceError(failure);
        }
    }

    public static OSSClient open(String endpoint, String region, String accessKey, String secret) {
        return OSSClient.newBuilder()
                .endpoint(endpoint)
                .region(region)
                .credentialsProvider(new StaticCredentialsProvider(accessKey, secret))
                .signatureVersion("v4")
                .connectTimeout(Duration.ofSeconds(5))
                .readWriteTimeout(Duration.ofSeconds(5))
                .retryer(new NopRetryer())
                .build();
    }

    public static void close(OSSClient client) {
        new ClientSession(client).close();
    }

    private record ClientSession(OSSClient client) implements AutoCloseable {
        @Override
        public void close() {
            try {
                client.close();
            } catch (RuntimeException failure) {
                throw failure;
            } catch (InterruptedException failure) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("Interrupted while closing the OSS client");
            } catch (Exception failure) {
                throw new IllegalStateException("Could not close the OSS client");
            }
        }
    }

    public static void requirePrivateUnversionedBucket(OSSClient client, String bucket) {
        var acl = client.getBucketAcl(GetBucketAclRequest.newBuilder().bucket(bucket).build())
                .accessControlPolicy();
        if (acl == null || acl.accessControlList() == null || !"private".equals(acl.accessControlList().grant())) {
            throw new InvalidBucketException("OSS requires a private bucket");
        }
        var versioning = client.getBucketVersioning(GetBucketVersioningRequest.newBuilder().bucket(bucket).build())
                .versioningConfiguration();
        String status = versioning == null ? null : versioning.status();
        if (status != null && !status.isEmpty() && !"Off".equals(status)) {
            throw new InvalidBucketException("OSS requires a bucket where versioning has never been enabled");
        }
    }

    static final class InvalidBucketException extends IllegalStateException {
        @Serial
        private static final long serialVersionUID = 1L;

        private InvalidBucketException(String message) {
            super(message);
        }
    }

    private static IllegalStateException serviceError(ServiceException failure) {
        return new IllegalStateException("OSS request failed (" + failure.errorCode()
                + ", request " + failure.requestId() + ")");
    }
}
