package io.github.iy88.project1.maintenance;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.DeleteMultipleObjectsRequest;
import com.aliyun.sdk.service.oss2.models.DeleteObject;
import com.aliyun.sdk.service.oss2.models.DeletedInfo;
import com.aliyun.sdk.service.oss2.models.ListObjectsV2Request;
import com.aliyun.sdk.service.oss2.models.ObjectSummary;
import io.github.iy88.project1.storage.OssClients;
import java.util.HashSet;

final class OssMaintenance {

    private static final long MAX_BATCH_SIZE = 1000;

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
    }

    String scope() {
        return "OSS " + endpoint + " bucket=" + bucket + " scope=ALL_OBJECTS";
    }

    long reset() {
        return OssClients.use(endpoint, region, accessKey, secret, client -> clear(client, bucket));
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
            var keys = objects.stream().map(ObjectSummary::key).toList();
            if (keys.getFirst().equals(previousFirstKey)) {
                throw new IllegalStateException("OSS listing did not advance after deletion");
            }
            previousFirstKey = keys.getFirst();
            var deletions = keys.stream().map(key -> DeleteObject.newBuilder().key(key).build()).toList();
            var result = client.deleteMultipleObjects(DeleteMultipleObjectsRequest.newBuilder()
                    .bucket(bucket).deleteObjects(deletions).quiet(false).build());
            var deleted = result.deletedObjects();
            if (deleted == null || !new HashSet<>(keys).equals(
                    new HashSet<>(deleted.stream().map(DeletedInfo::key).toList()))) {
                throw new IllegalStateException("OSS did not confirm every deletion in the batch");
            }
            removed += keys.size();
        }
    }
}
