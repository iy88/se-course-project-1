package io.github.iy88.project1.storage;

import com.aliyun.sdk.service.oss2.OSSClient;
import com.aliyun.sdk.service.oss2.models.GetObjectRequest;
import com.aliyun.sdk.service.oss2.models.GetObjectResult;
import com.aliyun.sdk.service.oss2.models.HeadObjectRequest;
import com.aliyun.sdk.service.oss2.models.HeadObjectResult;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class OssFileObjectsTests {
    private final OSSClient client = mock(OSSClient.class);
    private final OssFileObjects objects = new OssFileObjects(client, "v2-dev-fixture", "project1/dev");

    @Test
    void isolatesPurposeKeysWithinTheConfiguredBucket() {
        var image = objects.newLocation(FilePurpose.PRODUCT_IMAGE);
        var evidence = objects.newLocation(FilePurpose.CASE_EVIDENCE);
        assertThat(image.bucket()).isEqualTo("v2-dev-fixture");
        assertThat(evidence.bucket()).isEqualTo(image.bucket());
        assertThat(image.key()).startsWith("project1/dev/product_image/");
        assertThat(evidence.key()).startsWith("project1/dev/case_evidence/");
        assertThat(objects.newLocation(FilePurpose.PRODUCT_IMAGE)).isNotEqualTo(image);

        assertThatThrownBy(() -> objects.delete(new OssFileObjects.Location("v2-prod-fixture", image.key())))
                .isInstanceOf(OssFileObjects.Failure.class)
                .hasMessage("INVALID_CONFIGURATION");
        assertThatThrownBy(() -> objects.delete(new OssFileObjects.Location(image.bucket(), "project1/dev/probe/external")))
                .isInstanceOf(OssFileObjects.Failure.class)
                .hasMessage("INVALID_CONFIGURATION");
        verifyNoInteractions(client);
    }

    @Test
    void verifiesTheExpectedEtagBeforeAndAfterReading() {
        var location = objects.newLocation(FilePurpose.PRODUCT_IMAGE);
        var expected = new OssFileObjects.Metadata("\"example\"", 1L, "image/png");
        var response = mock(GetObjectResult.class);
        var head = mock(HeadObjectResult.class);
        when(response.eTag()).thenReturn(expected.etag());
        when(response.contentLength()).thenReturn(expected.sizeBytes());
        when(response.contentType()).thenReturn(expected.contentType());
        when(response.body()).thenAnswer(invocation -> new ByteArrayInputStream(new byte[] {42}));
        when(client.getObject(any(GetObjectRequest.class))).thenReturn(response);
        when(client.headObject(any(HeadObjectRequest.class))).thenReturn(head);
        when(head.eTag()).thenReturn(expected.etag(), "\"replaced\"");
        when(head.contentLength()).thenReturn(expected.sizeBytes());
        when(head.contentType()).thenReturn(expected.contentType());

        byte[] actual = objects.readForVerification(location, expected, InputStream::readAllBytes);
        assertThat(actual).containsExactly(42);
        var request = ArgumentCaptor.forClass(GetObjectRequest.class);
        verify(client).getObject(request.capture());
        assertThat(request.getValue().ifMatch()).isEqualTo(expected.etag());

        assertThatThrownBy(() -> objects.readForVerification(location, expected, InputStream::readAllBytes))
                .isInstanceOf(OssFileObjects.Failure.class)
                .hasMessage("CONTENT_CHANGED");
    }
}
