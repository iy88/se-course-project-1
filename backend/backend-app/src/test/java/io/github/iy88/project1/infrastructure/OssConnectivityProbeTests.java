package io.github.iy88.project1.infrastructure;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.AccessControlList;
import com.aliyun.sdk.service.oss2.models.AccessControlPolicy;
import com.aliyun.sdk.service.oss2.models.DeleteObjectRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketAclRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketAclResult;
import com.aliyun.sdk.service.oss2.models.GetBucketVersioningRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketVersioningResult;
import com.aliyun.sdk.service.oss2.models.GetObjectRequest;
import com.aliyun.sdk.service.oss2.models.GetObjectResult;
import com.aliyun.sdk.service.oss2.models.PutObjectRequest;
import com.aliyun.sdk.service.oss2.models.VersioningConfiguration;
import java.io.ByteArrayInputStream;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OssConnectivityProbeTests {

    private static final String BUCKET = "project1-dev";
    private static final String PREFIX = "project1/dev";

    @Test
    void deletesOnlyTheCreatedObjectWhenReadbackFails() {
        OSSClient client = privateBucket();
        var object = mock(GetObjectResult.class);
        when(object.body()).thenReturn(new ByteArrayInputStream(new byte[0]));
        when(client.getObject(any(GetObjectRequest.class))).thenReturn(object);

        assertThatThrownBy(() -> OssConnectivityProbe.verify(client, BUCKET, PREFIX))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("unexpected payload");

        var upload = ArgumentCaptor.forClass(PutObjectRequest.class);
        verify(client).putObject(upload.capture());
        assertThat(upload.getValue().bucket()).isEqualTo(BUCKET);
        assertThat(upload.getValue().key()).startsWith(PREFIX + "/probe/").endsWith(".txt");
        assertThat(upload.getValue().forbidOverwrite()).isTrue();
        var deletion = ArgumentCaptor.forClass(DeleteObjectRequest.class);
        verify(client).deleteObject(deletion.capture());
        assertThat(deletion.getValue().bucket()).isEqualTo(BUCKET);
        assertThat(deletion.getValue().key()).isEqualTo(upload.getValue().key());
    }

    @Test
    void refusesSuspendedVersioningBeforeWriting() {
        OSSClient client = privateBucket();
        var versioning = mock(GetBucketVersioningResult.class);
        when(versioning.versioningConfiguration())
                .thenReturn(VersioningConfiguration.newBuilder().status("Suspended").build());
        when(client.getBucketVersioning(any(GetBucketVersioningRequest.class))).thenReturn(versioning);

        assertThatThrownBy(() -> OssConnectivityProbe.verify(client, BUCKET, PREFIX))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("never been enabled");

        verify(client, never()).putObject(any(PutObjectRequest.class));
    }

    private static OSSClient privateBucket() {
        OSSClient client = mock(OSSClient.class);
        var acl = mock(GetBucketAclResult.class);
        when(acl.accessControlPolicy()).thenReturn(AccessControlPolicy.newBuilder()
                .accessControlList(AccessControlList.newBuilder().grant("private").build()).build());
        when(client.getBucketAcl(any(GetBucketAclRequest.class))).thenReturn(acl);
        when(client.getBucketVersioning(any(GetBucketVersioningRequest.class)))
                .thenReturn(mock(GetBucketVersioningResult.class));
        return client;
    }
}
