package io.github.iy88.project1.infrastructure;

import com.aliyun.oss.OSS;
import com.aliyun.oss.model.AccessControlList;
import com.aliyun.oss.model.BucketVersioningConfiguration;
import com.aliyun.oss.model.CannedAccessControlList;
import com.aliyun.oss.model.OSSObject;
import com.aliyun.oss.model.ObjectMetadata;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OssConnectivityProbeTests {

    private static final String BUCKET = "project1-dev";
    private static final String PREFIX = "project1/dev";

    @Test
    void deletesOnlyTheCreatedObjectWhenReadbackFails() {
        OSS client = mock(OSS.class);
        var acl = mock(AccessControlList.class);
        when(acl.getCannedACL()).thenReturn(CannedAccessControlList.Private);
        when(client.getBucketAcl(BUCKET)).thenReturn(acl);
        when(client.getBucketVersioning(BUCKET)).thenReturn(new BucketVersioningConfiguration());
        var object = new OSSObject();
        object.setObjectContent(new ByteArrayInputStream(new byte[0]));
        when(client.getObject(eq(BUCKET), any(String.class))).thenReturn(object);

        assertThatThrownBy(() -> OssConnectivityProbe.verify(client, BUCKET, PREFIX))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("unexpected payload");

        var key = org.mockito.ArgumentCaptor.forClass(String.class);
        var metadata = org.mockito.ArgumentCaptor.forClass(ObjectMetadata.class);
        verify(client).putObject(eq(BUCKET), key.capture(), any(InputStream.class), metadata.capture());
        assertThat(key.getValue()).startsWith(PREFIX + "/probe/").endsWith(".txt");
        assertThat(metadata.getValue().getRawMetadata()).containsEntry("x-oss-forbid-overwrite", "true");
        verify(client).deleteObject(BUCKET, key.getValue());
    }

    @Test
    void refusesSuspendedVersioningBeforeWriting() {
        OSS client = mock(OSS.class);
        var acl = mock(AccessControlList.class);
        when(acl.getCannedACL()).thenReturn(CannedAccessControlList.Private);
        when(client.getBucketAcl(BUCKET)).thenReturn(acl);
        when(client.getBucketVersioning(BUCKET)).thenReturn(
                new BucketVersioningConfiguration(BucketVersioningConfiguration.SUSPENDED));

        assertThatThrownBy(() -> OssConnectivityProbe.verify(client, BUCKET, PREFIX))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("never been enabled");

        verify(client, never()).putObject(any(), any(), any(InputStream.class), any());
    }
}
