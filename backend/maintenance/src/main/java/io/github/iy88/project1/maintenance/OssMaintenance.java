package io.github.iy88.project1.maintenance;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.Delete;
import com.aliyun.sdk.service.oss2.models.DeleteMultipleObjectsRequest;
import com.aliyun.sdk.service.oss2.models.ListObjectsV2Request;
import com.aliyun.sdk.service.oss2.models.ObjectIdentifier;
import io.github.iy88.project1.storage.OssClients;
import java.util.ArrayList;
import java.util.HashSet;

final class OssMaintenance {

    private static final long MAX_BATCH_SIZE = 1000;
    private static final String PREFIX_PATTERN = "[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*";

    private final String bucket;
    private final String region;
    private final String endpoint;
    private final String accessKey;
    private final String secret;

    OssMaintenance(MaintenanceConfig config) {
        bucket = config.matching("OSS_BUCKET", "[a-z0-9][a-z0-9-]{1,61}[a-z0-9]");
        region = config.matching("OSS_REGION", "[a-z0-9-]+");
        endpoint = config.required("OSS_ENDPOINT");
        String host = "https://oss-" + region;
        if (!endpoint.equals(host + ".aliyuncs.com") && !endpoint.equals(host + "-internal.aliyuncs.com")) {
            throw new IllegalArgumentException("OSS_ENDPOINT must be the HTTPS endpoint for OSS_REGION");
        }
        accessKey = config.required("OSS_ACCESS_KEY_ID");
        secret = config.required("OSS_ACCESS_KEY_SECRET");
        String configured = config.valueOrDefault("OSS_PREFIX", "").strip();
        if (!configured.isEmpty()) {
            normalizePrefix(configured);
        }
    }

    String scope() {
        return "OSS " + endpoint + " bucket=" + bucket + " scope=ALL_OBJECTS";
    }

    /** Scope for an explicit, nonempty, segment-bounded deployment prefix. */
    String prefixScope(String prefix) {
        return "OSS " + endpoint + " bucket=" + bucket + " scope=PREFIX " + normalizePrefix(prefix) + "/";
    }

    long reset() {
        return OssClients.use(endpoint, region, accessKey, secret, client -> clear(client, bucket));
    }

    long resetPrefix(String prefix) {
        String normalized = normalizePrefix(prefix);
        return OssClients.use(endpoint, region, accessKey, secret,
                client -> clearPrefix(client, bucket, normalized));
    }

    static long clear(OSSClient client, String bucket) {
        OssClients.requirePrivateUnversionedBucket(client, bucket);
        var request = ListObjectsV2Request.newBuilder().bucket(bucket).maxKeys(MAX_BATCH_SIZE).build();
        long removed = 0;
        String previousFirstKey = null;
        while (true) {
            // List the first page again after deleting it, so a continuation token never points into removed objects.
            var page = client.listObjectsV2(request);
            var objects = page.contents();
            if (objects == null || objects.isEmpty()) {
                if (Boolean.TRUE.equals(page.isTruncated())) {
                    throw new IllegalStateException("OSS returned an empty truncated page");
                }
                return removed;
            }
            if (objects.size() > MAX_BATCH_SIZE) {
                throw new IllegalStateException("OSS returned more keys than the batch delete limit");
            }
            var keys = new ArrayList<String>(objects.size());
            for (var object : objects) {
                String key = object == null ? null : object.key();
                if (key == null || key.isEmpty()) {
                    throw new IllegalStateException("OSS listing returned an object without a key");
                }
                keys.add(key);
            }
            if (keys.getFirst().equals(previousFirstKey)) {
                throw new IllegalStateException("OSS listing did not advance after deletion");
            }
            previousFirstKey = keys.getFirst();
            var deletions = keys.stream().map(key -> ObjectIdentifier.newBuilder().key(key).build()).toList();
            var result = client.deleteMultipleObjects(DeleteMultipleObjectsRequest.newBuilder()
                    .bucket(bucket)
                    .delete(Delete.newBuilder().objects(deletions).quiet(false).build())
                    .build());
            var deleted = result.deletedObjects();
            var confirmedKeys = new HashSet<String>();
            if (deleted != null) {
                for (var object : deleted) {
                    String key = object == null ? null : object.key();
                    if (key == null || key.isEmpty()) {
                        throw new IllegalStateException("OSS deletion response returned an object without a key");
                    }
                    confirmedKeys.add(key);
                }
            }
            if (!new HashSet<>(keys).equals(confirmedKeys)) {
                throw new IllegalStateException("OSS did not confirm every deletion in the batch");
            }
            removed += keys.size();
        }
    }

    /**
     * Removes only objects below {@code prefix/}. The trailing slash and the per-key boundary
     * check keep a deployment such as {@code project1/dev} from touching {@code project1/dev2}.
     * Empty prefixes are rejected so callers cannot accidentally request a whole-bucket reset
     * through the scoped path.
     */
    static long clearPrefix(OSSClient client, String bucket, String prefix) {
        String normalized = normalizePrefix(prefix);
        String scope = normalized + "/";
        OssClients.requirePrivateUnversionedBucket(client, bucket);
        var request = ListObjectsV2Request.newBuilder()
                .bucket(bucket)
                .prefix(scope)
                .maxKeys(MAX_BATCH_SIZE)
                .build();
        long removed = 0;
        String previousFirstKey = null;
        while (true) {
            var page = client.listObjectsV2(request);
            var objects = page.contents();
            if (objects == null || objects.isEmpty()) {
                if (Boolean.TRUE.equals(page.isTruncated())) {
                    throw new IllegalStateException("OSS returned an empty truncated prefix page");
                }
                return removed;
            }
            if (objects.size() > MAX_BATCH_SIZE) {
                throw new IllegalStateException("OSS returned more keys than the batch delete limit");
            }
            var keys = new ArrayList<String>(objects.size());
            for (var object : objects) {
                String key = object == null ? null : object.key();
                if (key == null || !key.startsWith(scope) || key.length() == scope.length()) {
                    throw new IllegalStateException("OSS returned a key outside the configured prefix");
                }
                keys.add(key);
            }
            if (keys.getFirst().equals(previousFirstKey)) {
                throw new IllegalStateException("OSS listing did not advance after deletion");
            }
            previousFirstKey = keys.getFirst();
            var deletions = keys.stream().map(key -> ObjectIdentifier.newBuilder().key(key).build()).toList();
            var result = client.deleteMultipleObjects(DeleteMultipleObjectsRequest.newBuilder()
                    .bucket(bucket)
                    .delete(Delete.newBuilder().objects(deletions).quiet(false).build())
                    .build());
            var deleted = result.deletedObjects();
            var confirmedKeys = new HashSet<String>();
            if (deleted != null) {
                for (var object : deleted) {
                    String key = object == null ? null : object.key();
                    if (key == null || !key.startsWith(scope)) {
                        throw new IllegalStateException("OSS returned a deletion outside the configured prefix");
                    }
                    confirmedKeys.add(key);
                }
            }
            if (!new HashSet<>(keys).equals(confirmedKeys)) {
                throw new IllegalStateException("OSS did not confirm every prefix deletion in the batch");
            }
            removed += keys.size();
        }
    }

    static String normalizePrefix(String value) {
        if (value == null || value.isEmpty() || value.length() > 128
                || value.startsWith("/") || value.endsWith("/") || value.contains("//")
                || !value.matches(PREFIX_PATTERN)) {
            throw new IllegalArgumentException(
                    "OSS prefix must be a nonempty, segment-bounded prefix such as project1/dev");
        }
        return value;
    }
}
