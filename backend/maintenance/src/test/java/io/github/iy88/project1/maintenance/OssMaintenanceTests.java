package io.github.iy88.project1.maintenance;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.AccessControlList;
import com.aliyun.sdk.service.oss2.models.AccessControlPolicy;
import com.aliyun.sdk.service.oss2.models.DeleteMultipleObjectsRequest;
import com.aliyun.sdk.service.oss2.models.DeleteMultipleObjectsResult;
import com.aliyun.sdk.service.oss2.models.DeleteObject;
import com.aliyun.sdk.service.oss2.models.DeleteObjectRequest;
import com.aliyun.sdk.service.oss2.models.DeletedInfo;
import com.aliyun.sdk.service.oss2.models.GetBucketAclRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketAclResult;
import com.aliyun.sdk.service.oss2.models.GetBucketVersioningRequest;
import com.aliyun.sdk.service.oss2.models.GetBucketVersioningResult;
import com.aliyun.sdk.service.oss2.models.ListObjectsV2Request;
import com.aliyun.sdk.service.oss2.models.ListObjectsV2Result;
import com.aliyun.sdk.service.oss2.models.ObjectSummary;
import com.aliyun.sdk.service.oss2.models.VersioningConfiguration;
import java.util.Arrays;
import java.util.stream.IntStream;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OssMaintenanceTests {

    private static final String BUCKET = "project1-dev";

    @Test
    void clearsTheWholeBucketInBatchesOfAtMostOneThousandObjects() {
        OSSClient client = privateBucket();
        String[] firstBatch = IntStream.range(0, 1000).mapToObj(index -> "project1/dev/" + index)
                .toArray(String[]::new);
        var first = page(firstBatch);
        var second = page("outside/one", "root-object");
        var empty = page();
        when(client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(first, second, empty);
        when(client.deleteMultipleObjects(any(DeleteMultipleObjectsRequest.class))).thenAnswer(invocation -> {
            DeleteMultipleObjectsRequest request = invocation.getArgument(0);
            return deleted(request.deleteObjects().stream().map(DeleteObject::key).toArray(String[]::new));
        });

        assertThat(OssMaintenance.clear(client, BUCKET)).isEqualTo(1002);
        var deletes = ArgumentCaptor.forClass(DeleteMultipleObjectsRequest.class);
        verify(client, times(2)).deleteMultipleObjects(deletes.capture());
        assertThat(deletes.getAllValues()).allSatisfy(request -> {
            assertThat(request.bucket()).isEqualTo(BUCKET);
            assertThat(request.quiet()).isFalse();
        });
        assertThat(deletes.getAllValues().get(0).deleteObjects()).extracting(DeleteObject::key)
                .containsExactly(firstBatch);
        assertThat(deletes.getAllValues().get(1).deleteObjects()).extracting(DeleteObject::key)
                .containsExactly("outside/one", "root-object");
        verify(client, never()).deleteObject(any(DeleteObjectRequest.class));
        var requests = ArgumentCaptor.forClass(ListObjectsV2Request.class);
        verify(client, times(3)).listObjectsV2(requests.capture());
        assertThat(requests.getAllValues()).allSatisfy(request -> {
            assertThat(request.bucket()).isEqualTo(BUCKET);
            assertThat(request.prefix()).isNullOrEmpty();
            assertThat(request.maxKeys()).isEqualTo(1000L);
            assertThat(request.continuationToken()).isNull();
        });
    }

    @Test
    void stopsWhenOssDoesNotConfirmTheWholeBatch() {
        OSSClient client = privateBucket();
        var listed = page("first", "second");
        var removed = deleted("first");
        when(client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(listed);
        when(client.deleteMultipleObjects(any(DeleteMultipleObjectsRequest.class))).thenReturn(removed);

        assertThatThrownBy(() -> OssMaintenance.clear(client, BUCKET))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("did not confirm");
        verify(client).listObjectsV2(any(ListObjectsV2Request.class));
    }

    @Test
    void refusesVersionedBucketsBeforeListing() {
        OSSClient client = privateBucket();
        var versioning = mock(GetBucketVersioningResult.class);
        when(versioning.versioningConfiguration())
                .thenReturn(VersioningConfiguration.newBuilder().status("Suspended").build());
        when(client.getBucketVersioning(any(GetBucketVersioningRequest.class))).thenReturn(versioning);

        assertThatThrownBy(() -> OssMaintenance.clear(client, BUCKET))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("versioning");
        verify(client, never()).listObjectsV2(any(ListObjectsV2Request.class));
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

    private static ListObjectsV2Result page(String... keys) {
        var page = mock(ListObjectsV2Result.class);
        when(page.contents()).thenReturn(Arrays.stream(keys)
                .map(key -> ObjectSummary.newBuilder().key(key).build()).toList());
        return page;
    }

    private static DeleteMultipleObjectsResult deleted(String... keys) {
        var result = mock(DeleteMultipleObjectsResult.class);
        when(result.deletedObjects()).thenReturn(Arrays.stream(keys)
                .map(key -> DeletedInfo.newBuilder().key(key).build()).toList());
        return result;
    }
}
