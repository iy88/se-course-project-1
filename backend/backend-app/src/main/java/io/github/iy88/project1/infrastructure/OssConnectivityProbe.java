package io.github.iy88.project1.infrastructure;

import com.aliyun.oss.ClientBuilderConfiguration;
import com.aliyun.oss.ClientException;
import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import com.aliyun.oss.OSSException;
import com.aliyun.oss.common.auth.DefaultCredentialProvider;
import com.aliyun.oss.common.comm.SignVersion;
import com.aliyun.oss.model.BucketVersioningConfiguration;
import com.aliyun.oss.model.CannedAccessControlList;
import com.aliyun.oss.model.ObjectMetadata;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.UUID;
import org.springframework.util.Assert;

class OssConnectivityProbe {

    static void verify(ExternalProbeProperties.Oss settings) {
        var configuration = new ClientBuilderConfiguration();
        configuration.setSignatureVersion(SignVersion.V4);
        configuration.setConnectionTimeout(5000);
        configuration.setSocketTimeout(5000);
        configuration.setMaxErrorRetry(0);

        OSS client = OSSClientBuilder.create()
                .endpoint(settings.endpoint())
                .region(settings.region())
                .credentialsProvider(new DefaultCredentialProvider(settings.accessKeyId(), settings.accessKeySecret()))
                .clientConfiguration(configuration)
                .build();
        try {
            verify(client, settings.bucket(), settings.prefix());
        } catch (OSSException exception) {
            throw new IllegalStateException("OSS probe failed with service code " + exception.getErrorCode()
                    + " (request " + exception.getRequestId() + ")");
        } catch (ClientException exception) {
            throw new IllegalStateException("OSS probe connection failed (" + exception.getErrorCode() + ")");
        } catch (IOException exception) {
            throw new IllegalStateException("OSS probe could not read the response body");
        } finally {
            client.shutdown();
        }
    }

    static void verify(OSS client, String bucket, String prefix) throws IOException {
        Assert.state(client.getBucketAcl(bucket).getCannedACL() == CannedAccessControlList.Private,
                "OSS probe requires a private bucket");
        String versioning = client.getBucketVersioning(bucket).getStatus();
        Assert.state(versioning == null || versioning.isEmpty()
                        || BucketVersioningConfiguration.OFF.equals(versioning),
                "OSS probe requires a bucket where versioning has never been enabled");

        String key = prefix + "/probe/" + UUID.randomUUID() + ".txt";
        byte[] payload = ("Project1 S1 OSS probe " + UUID.randomUUID()).getBytes(StandardCharsets.UTF_8);
        var metadata = new ObjectMetadata();
        metadata.setContentType("text/plain");
        metadata.setContentLength(payload.length);
        metadata.setHeader("x-oss-forbid-overwrite", "true");
        client.putObject(bucket, key, new ByteArrayInputStream(payload), metadata);
        try (var object = client.getObject(bucket, key)) {
            byte[] actual = object.getObjectContent().readNBytes(payload.length + 1);
            Assert.state(Arrays.equals(payload, actual), "OSS probe read an unexpected payload");
        } finally {
            client.deleteObject(bucket, key);
        }
    }
}
