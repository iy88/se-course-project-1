package io.github.iy88.project1.infrastructure;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.DeleteObjectRequest;
import com.aliyun.sdk.service.oss2.models.GetObjectRequest;
import com.aliyun.sdk.service.oss2.models.PutObjectRequest;
import com.aliyun.sdk.service.oss2.transport.BinaryData;
import io.github.iy88.project1.storage.OssClients;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.UUID;

class OssConnectivityProbe {

    static void verify(ExternalProbeProperties.Oss settings) {
        OssClients.use(settings.endpoint(), settings.region(), settings.accessKeyId(), settings.accessKeySecret(),
                client -> {
                    verify(client, settings.bucket(), settings.prefix());
                    return null;
                });
    }

    static void verify(OSSClient client, String bucket, String prefix) {
        OssClients.requirePrivateUnversionedBucket(client, bucket);

        String key = prefix + "/probe/" + UUID.randomUUID() + ".txt";
        byte[] payload = ("Project1 S1 OSS probe " + UUID.randomUUID()).getBytes(StandardCharsets.UTF_8);
        client.putObject(PutObjectRequest.newBuilder()
                .bucket(bucket)
                .key(key)
                .contentType("text/plain")
                .forbidOverwrite(true)
                .body(BinaryData.fromBytes(payload))
                .build());
        try (var body = client.getObject(GetObjectRequest.newBuilder().bucket(bucket).key(key).build()).body()) {
            byte[] actual = body.readNBytes(payload.length + 1);
            if (!Arrays.equals(payload, actual)) {
                throw new IllegalStateException("OSS probe read an unexpected payload");
            }
        } catch (IOException failure) {
            throw new IllegalStateException("OSS probe could not read the response body");
        } finally {
            client.deleteObject(DeleteObjectRequest.newBuilder().bucket(bucket).key(key).build());
        }
    }
}
