package io.github.iy88.project1.maintenance;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.HeadObjectRequest;
import com.aliyun.sdk.service.oss2.models.ListObjectsV2Request;
import com.aliyun.sdk.service.oss2.models.PutObjectRequest;
import com.aliyun.sdk.service.oss2.transport.BinaryData;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Real OSS upload plus the exact metadata needed by file_record. */
class SeedFiles {
    private final SeedContext context;

    SeedFiles(SeedContext context) {
        this.context = context;
    }

    void requirePrefixEmpty() {
        OssClients.use(context.endpoint(), context.region(), accessKey(), secret(), client -> {
            OssClients.requirePrivateUnversionedBucket(client, context.bucket());
            var page = client.listObjectsV2(ListObjectsV2Request.newBuilder()
                    .bucket(context.bucket())
                    .prefix(context.prefix() + "/")
                    .maxKeys(1L)
                    .build());
            if (page.contents() != null && !page.contents().isEmpty()) {
                String scope = context.prefix() + "/";
                for (var object : page.contents()) {
                    if (object == null || object.key() == null || !object.key().startsWith(scope)) {
                        throw new IllegalStateException("OSS listed an object outside OSS_PREFIX");
                    }
                }
                throw new IllegalStateException("OSS_PREFIX is not empty. Run oss reset with the matching "
                        + "--prefix preview and confirmation before seeding.");
            }
            return null;
        });
    }

    List<UploadedFile> uploadAll(List<SeedSupport.SeedAsset> assets) {
        List<UploadedFile> uploaded = new ArrayList<>(assets.size());
        OssClients.use(context.endpoint(), context.region(), accessKey(), secret(), client -> {
            OssClients.requirePrivateUnversionedBucket(client, context.bucket());
            for (var asset : assets) {
                byte[] bytes = asset.bytes();
                // Allocate the key through the same deployment-scoped storage capability used by the app.
                String key = new OssFileObjects(client, context.bucket(), context.prefix())
                        .newLocation(asset.purpose()).key();
                var result = client.putObject(PutObjectRequest.newBuilder()
                        .bucket(context.bucket())
                        .key(key)
                        .forbidOverwrite(true)
                        .contentType(asset.contentType())
                        .body(BinaryData.fromBytes(bytes))
                        .build());
                if (result.eTag() == null || result.eTag().isBlank()) {
                    throw new IllegalStateException("OSS upload returned no ETag for " + asset.name());
                }
                uploaded.add(new UploadedFile(asset, key, result.eTag(), bytes.length,
                        SeedSupport.sha256Hex(bytes), bytes));
            }
            return null;
        });
        return List.copyOf(uploaded);
    }

    void verifySamples(List<UploadedFile> files, int samples) {
        if (files.isEmpty() || samples <= 0) {
            return;
        }
        OssClients.use(context.endpoint(), context.region(), accessKey(), secret(), client -> {
            OssClients.requirePrivateUnversionedBucket(client, context.bucket());
            int step = Math.max(1, files.size() / samples);
            for (int index = 0; index < files.size() && index / step < samples; index += step) {
                var file = files.get(index);
                var head = client.headObject(HeadObjectRequest.newBuilder()
                        .bucket(context.bucket()).key(file.objectKey()).build());
                if (!Objects.equals(head.contentLength(), (long) file.sizeBytes())
                        || !Objects.equals(head.eTag(), file.eTag())) {
                    throw new IllegalStateException("OSS object does not match its seeded metadata: "
                            + file.asset().name());
                }
            }
            return null;
        });
    }

    private String accessKey() {
        return context.config().required("OSS_ACCESS_KEY_ID");
    }

    private String secret() {
        return context.config().required("OSS_ACCESS_KEY_SECRET");
    }

    record UploadedFile(SeedSupport.SeedAsset asset, String objectKey, String eTag, int sizeBytes,
                        String sha256, byte[] bytes) {
        String purpose() {
            return asset.purpose().value();
        }
    }
}
