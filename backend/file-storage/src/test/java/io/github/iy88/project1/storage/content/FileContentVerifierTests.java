package io.github.iy88.project1.storage.content;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import javax.imageio.ImageIO;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class FileContentVerifierTests {
    @Test
    void verifiesActualFormatAndFileSize() throws Exception {
        for (String format : new String[] {"png", "jpeg"}) {
            byte[] payload = image(format);
            String mime = "image/" + format;
            var verified = FileContentVerifier.verify(new ByteArrayInputStream(payload), payload.length, mime, 4096);
            assertThat(verified.contentType()).isEqualTo(mime);
            assertThat(verified.sizeBytes()).isEqualTo(payload.length);
        }
    }

    @Test
    void rejectsSpoofedTypeAndSavedSizeViolations() throws Exception {
        byte[] png = image("png");
        assertInvalid(png, png.length, "image/jpeg", 4096);
        assertInvalid(png, png.length - 1, "image/png", 4096);
        assertInvalid(png, png.length + 1, "image/png", 4096);
        assertInvalid(png, png.length, "image/png", png.length - 1);
    }

    @Test
    void acceptsImagesAboveThePreviouslyProposedPixelLimit() throws Exception {
        var output = new ByteArrayOutputStream();
        var large = new BufferedImage(6000, 4300, BufferedImage.TYPE_BYTE_BINARY);
        assertThat(ImageIO.write(large, "png", output)).isTrue();
        var verified = FileContentVerifier.verify(new ByteArrayInputStream(output.toByteArray()), output.size(),
                "image/png", 104857600);
        assertThat(verified.sizeBytes()).isEqualTo(output.size());
    }

    @Test
    void parsesPdfAndRejectsTruncatedOrDisguisedPdf() throws Exception {
        var output = new ByteArrayOutputStream();
        try (var pdf = new PDDocument()) {
            pdf.addPage(new PDPage());
            pdf.save(output);
        }
        byte[] bytes = output.toByteArray();
        assertThat(FileContentVerifier.verify(new ByteArrayInputStream(bytes), bytes.length, "application/pdf", 4096)
                .contentType()).isEqualTo("application/pdf");
        assertInvalid(bytes, bytes.length, "image/png", 4096);
        byte[] truncated = java.util.Arrays.copyOf(bytes, bytes.length / 2);
        assertInvalid(truncated, truncated.length, "application/pdf", 4096);
        byte[] png = image("png");
        assertInvalid(png, png.length, "application/pdf", 4096);
    }

    private static void assertInvalid(byte[] bytes, long length, String mime, long maxBytes) {
        assertThatThrownBy(() -> FileContentVerifier.verify(new ByteArrayInputStream(bytes), length, mime, maxBytes))
                .isInstanceOf(FileContentVerifier.InvalidContent.class);
    }

    private static byte[] image(String format) throws IOException {
        var output = new ByteArrayOutputStream();
        assertThat(ImageIO.write(new BufferedImage(2, 2, BufferedImage.TYPE_INT_RGB), format, output)).isTrue();
        return output.toByteArray();
    }
}
