package io.github.iy88.project1.storage;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.credentials.StaticCredentialsProvider;
import com.aliyun.sdk.service.oss2.exceptions.OperationException;
import com.aliyun.sdk.service.oss2.exceptions.ServiceException;
import com.aliyun.sdk.service.oss2.models.GetBucketAclRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketVersioningRequest;
import com.aliyun.sdk.service.oss2.retry.NopRetryer;
import java.time.Duration;
import java.util.function.Function;

public final class OssClients {

    private OssClients() {
    }

    public static <T> T use(String endpoint, String region, String accessKey, String secret,
                            Function<OSSClient, T> action) {
        try (OSSClient client = OSSClient.newBuilder()
                .endpoint(endpoint)
                .region(region)
                .credentialsProvider(new StaticCredentialsProvider(accessKey, secret))
                .signatureVersion("v4")
                .connectTimeout(Duration.ofSeconds(5))
                .readWriteTimeout(Duration.ofSeconds(5))
                .retryer(new NopRetryer())
                .build()) {
            return action.apply(client);
        } catch (OperationException failure) {
            if (failure.getCause() instanceof ServiceException serviceFailure) {
                throw serviceError(serviceFailure);
            }
            throw new IllegalStateException("OSS request failed (" + failure.getClass().getSimpleName() + ")");
        } catch (ServiceException failure) {
            throw serviceError(failure);
        } catch (RuntimeException failure) {
            throw failure;
        } catch (Exception failure) {
            throw new IllegalStateException("Could not close the OSS client");
        }
    }

    public static void requirePrivateUnversionedBucket(OSSClient client, String bucket) {
        var acl = client.getBucketAcl(GetBucketAclRequest.newBuilder().bucket(bucket).build())
                .accessControlPolicy();
        if (acl == null || acl.accessControlList() == null || !"private".equals(acl.accessControlList().grant())) {
            throw new IllegalStateException("OSS requires a private bucket");
        }
        var versioning = client.getBucketVersioning(GetBucketVersioningRequest.newBuilder().bucket(bucket).build())
                .versioningConfiguration();
        String status = versioning == null ? null : versioning.status();
        if (status != null && !status.isEmpty() && !"Off".equals(status)) {
            throw new IllegalStateException("OSS requires a bucket where versioning has never been enabled");
        }
    }

    private static IllegalStateException serviceError(ServiceException failure) {
        return new IllegalStateException("OSS request failed (" + failure.errorCode()
                + ", request " + failure.requestId() + ")");
    }
}
