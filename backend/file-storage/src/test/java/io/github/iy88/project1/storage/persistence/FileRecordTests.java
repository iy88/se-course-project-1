package io.github.iy88.project1.storage.persistence;

import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import java.time.Instant;
import java.util.Set;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

class FileRecordTests {
    @Test
    void concurrentCompletionAcceptsTheSameObjectAndRejectsAChangedEtag() {
        var created = Instant.parse("2026-11-19T00:00:00Z");
        var record = new FileRecord(new UploadRegistration(1, FilePurpose.PRODUCT_IMAGE, null,
                new Location("dev-fixture", "dev/product_image/example"), 64, "image/png",
                new UploadRegistration.Rules("test", 128, Set.of("image/png")), "test",
                created, created.plusSeconds(60), created.plusSeconds(120)));
        var content = new VerifiedContent(64, "image/png");

        record.markVerified("\"first\"", content, created.plusSeconds(1));
        record.markVerified("\"first\"", content, created.plusSeconds(2));

        assertThatThrownBy(() -> record.markVerified("\"changed\"", content, created.plusSeconds(3)))
                .isInstanceOf(FileRegistry.Rejected.class)
                .hasMessage("FILE_CONTENT_CHANGED");
    }
}
