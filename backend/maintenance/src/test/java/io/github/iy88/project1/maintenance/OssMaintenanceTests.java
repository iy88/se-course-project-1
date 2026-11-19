package io.github.iy88.project1.maintenance;

import com.aliyun.oss.OSS;
import com.aliyun.oss.model.AccessControlList;
import com.aliyun.oss.model.BucketVersioningConfiguration;
import com.aliyun.oss.model.CannedAccessControlList;
import com.aliyun.oss.model.DeleteObjectsRequest;
import com.aliyun.oss.model.DeleteObjectsResult;
import com.aliyun.oss.model.ListObjectsV2Request;
import com.aliyun.oss.model.ListObjectsV2Result;
import com.aliyun.oss.model.OSSObjectSummary;
import java.util.List;
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
        OSS client = privateBucket();
        String[] firstBatch = IntStream.range(0, 1000).mapToObj(index -> "project1/dev/" + index)
                .toArray(String[]::new);
        when(client.listObjectsV2(any(ListObjectsV2Request.class)))
                .thenReturn(page(firstBatch), page("outside/one", "root-object"), page());
        when(client.deleteObjects(any(DeleteObjectsRequest.class))).thenAnswer(invocation -> {
            DeleteObjectsRequest request = invocation.getArgument(0);
            return new DeleteObjectsResult(request.getKeys());
        });

        assertThat(OssMaintenance.clear(client, BUCKET)).isEqualTo(1002);
        var deletes = ArgumentCaptor.forClass(DeleteObjectsRequest.class);
        verify(client, times(2)).deleteObjects(deletes.capture());
        assertThat(deletes.getAllValues()).allSatisfy(request -> {
            assertThat(request.getBucketName()).isEqualTo(BUCKET);
            assertThat(request.isQuiet()).isFalse();
        });
        assertThat(deletes.getAllValues().get(0).getKeys()).containsExactly(firstBatch);
        assertThat(deletes.getAllValues().get(1).getKeys()).containsExactly("outside/one", "root-object");
        verify(client, never()).deleteObject(any(String.class), any(String.class));
        var requests = ArgumentCaptor.forClass(ListObjectsV2Request.class);
        verify(client, times(3)).listObjectsV2(requests.capture());
        assertThat(requests.getAllValues()).allSatisfy(request -> {
            assertThat(request.getBucketName()).isEqualTo(BUCKET);
            assertThat(request.getPrefix()).isNullOrEmpty();
            assertThat(request.getMaxKeys()).isEqualTo(1000);
            assertThat(request.getContinuationToken()).isNull();
        });
    }

    @Test
    void stopsWhenOssDoesNotConfirmTheWholeBatch() {
        OSS client = privateBucket();
        when(client.listObjectsV2(any(ListObjectsV2Request.class)))
                .thenReturn(page("first", "second"));
        when(client.deleteObjects(any(DeleteObjectsRequest.class)))
                .thenReturn(new DeleteObjectsResult(List.of("first")));

        assertThatThrownBy(() -> OssMaintenance.clear(client, BUCKET))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("did not confirm");
        verify(client).listObjectsV2(any(ListObjectsV2Request.class));
    }

    @Test
    void refusesVersionedBucketsBeforeListing() {
        OSS client = privateBucket();
        when(client.getBucketVersioning(BUCKET)).thenReturn(
                new BucketVersioningConfiguration(BucketVersioningConfiguration.SUSPENDED));

        assertThatThrownBy(() -> OssMaintenance.clear(client, BUCKET))
                .isInstanceOf(IllegalStateException.class).hasMessageContaining("versioning");
        verify(client, never()).listObjectsV2(any(ListObjectsV2Request.class));
    }

    private static OSS privateBucket() {
        OSS client = mock(OSS.class);
        var acl = mock(AccessControlList.class);
        when(acl.getCannedACL()).thenReturn(CannedAccessControlList.Private);
        when(client.getBucketAcl(BUCKET)).thenReturn(acl);
        when(client.getBucketVersioning(BUCKET)).thenReturn(new BucketVersioningConfiguration());
        return client;
    }

    private static ListObjectsV2Result page(String... keys) {
        var page = new ListObjectsV2Result();
        for (String key : keys) {
            var object = new OSSObjectSummary();
            object.setKey(key);
            page.getObjectSummaries().add(object);
        }
        return page;
    }

}
