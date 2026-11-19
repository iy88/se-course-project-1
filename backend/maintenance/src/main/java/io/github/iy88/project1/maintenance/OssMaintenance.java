package io.github.iy88.project1.maintenance;

import com.aliyun.oss.ClientBuilderConfiguration;
import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import com.aliyun.oss.common.auth.DefaultCredentialProvider;
import com.aliyun.oss.common.comm.SignVersion;
import com.aliyun.oss.model.BucketVersioningConfiguration;
import com.aliyun.oss.model.CannedAccessControlList;
import com.aliyun.oss.model.DeleteObjectsRequest;
import com.aliyun.oss.model.ListObjectsV2Request;
import com.aliyun.oss.model.OSSObjectSummary;
import java.util.HashSet;

final class OssMaintenance {

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
        var options = new ClientBuilderConfiguration();
        options.setSignatureVersion(SignVersion.V4);
        options.setConnectionTimeout(5000);
        options.setSocketTimeout(5000);
        options.setMaxErrorRetry(0);
        OSS client = OSSClientBuilder.create()
                .endpoint(endpoint)
                .region(region)
                .credentialsProvider(new DefaultCredentialProvider(accessKey, secret))
                .clientConfiguration(options)
                .build();
        try {
            return clear(client, bucket);
        } finally {
            client.shutdown();
        }
    }

    static long clear(OSS client, String bucket) {
        if (client.getBucketAcl(bucket).getCannedACL() != CannedAccessControlList.Private) {
            throw new IllegalStateException("OSS reset requires a private bucket");
        }
        String status = client.getBucketVersioning(bucket).getStatus();
        if (status != null && !status.isEmpty() && !BucketVersioningConfiguration.OFF.equals(status)) {
            throw new IllegalStateException("OSS reset requires a bucket where versioning has never been enabled");
        }
        var request = new ListObjectsV2Request(bucket);
        int batchSize = DeleteObjectsRequest.DELETE_OBJECTS_ONETIME_LIMIT;
        request.setMaxKeys(batchSize);
        long removed = 0;
        String previousFirstKey = null;
        while (true) {
            // List the first page again after deleting it, so a continuation token never points into removed objects.
            var page = client.listObjectsV2(request);
            var keys = page.getObjectSummaries().stream().map(OSSObjectSummary::getKey).toList();
            if (keys.isEmpty()) {
                if (page.isTruncated()) {
                    throw new IllegalStateException("OSS returned an empty truncated page");
                }
                return removed;
            }
            if (keys.size() > batchSize) {
                throw new IllegalStateException("OSS returned more keys than the batch delete limit");
            }
            if (keys.getFirst().equals(previousFirstKey)) {
                throw new IllegalStateException("OSS listing did not advance after deletion");
            }
            previousFirstKey = keys.getFirst();
            var result = client.deleteObjects(new DeleteObjectsRequest(bucket).withKeys(keys).withQuiet(false));
            var deleted = result.getDeletedObjects();
            if (deleted == null || !new HashSet<>(keys).equals(new HashSet<>(deleted))) {
                throw new IllegalStateException("OSS did not confirm every deletion in the batch");
            }
            removed += keys.size();
        }
    }
}
