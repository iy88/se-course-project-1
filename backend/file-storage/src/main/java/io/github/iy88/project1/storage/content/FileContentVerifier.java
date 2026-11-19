package io.github.iy88.project1.storage.content;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.imageio.ImageIO;
import org.apache.pdfbox.io.RandomAccessReadBufferedFile;
import org.apache.pdfbox.pdfparser.PDFParser;

/** Verifies the actual file bytes using the rules saved at authorization. */
public final class FileContentVerifier {
    private static final String PDF = "application/pdf";
    private static final int SAMPLE_EDGE = 1024;

    private FileContentVerifier() {}

    public static boolean isImage(String contentType) {
        return "image/jpeg".equals(contentType) || "image/png".equals(contentType);
    }

    public static boolean supports(String contentType) {
        return isImage(contentType) || PDF.equals(contentType);
    }

    public static VerifiedContent verify(InputStream source, long declaredBytes, String declaredMime,
                                         long maxBytes) throws IOException {
        if (declaredBytes <= 0 || declaredBytes > maxBytes || !supports(declaredMime)) {
            throw new InvalidContent();
        }
        Path file = Files.createTempFile("project1-verify-", ".upload");
        try {
            copyExactLength(source, file, declaredBytes);
            if (PDF.equals(declaredMime)) {
                verifyPdf(file);
            } else {
                verifyImage(file, declaredMime);
            }
            return new VerifiedContent(declaredBytes, declaredMime);
        } finally {
            Files.deleteIfExists(file);
        }
    }

    private static void copyExactLength(InputStream source, Path destination, long length) throws IOException {
        byte[] buffer = new byte[8192];
        try (var output = Files.newOutputStream(destination)) {
            long remaining = length;
            while (remaining > 0) {
                int count = source.readNBytes(buffer, 0, (int) Math.min(remaining, buffer.length));
                if (count == 0) {
                    throw new InvalidContent();
                }
                output.write(buffer, 0, count);
                remaining -= count;
            }
            if (source.read() != -1) {
                throw new InvalidContent();
            }
        }
    }

    private static void verifyImage(Path file, String mime) throws IOException {
        try (var image = ImageIO.createImageInputStream(file.toFile())) {
            if (image == null) {
                throw new IOException("Could not open the staged image for verification");
            }
            var readers = ImageIO.getImageReaders(image);
            if (!readers.hasNext()) {
                throw new InvalidContent();
            }
            var reader = readers.next();
            try {
                String format = reader.getFormatName().toLowerCase(Locale.ROOT);
                if (!mime.equals("image/" + format)) {
                    throw new InvalidContent();
                }
                reader.setInput(image, true, true);
                int stride = Math.ceilDiv(Math.max(reader.getWidth(0), reader.getHeight(0)), SAMPLE_EDGE);
                var readParameters = reader.getDefaultReadParam();
                // Bound the decoded raster without rejecting an image by its dimensions.
                readParameters.setSourceSubsampling(stride, stride, 0, 0);
                var warning = new AtomicBoolean();
                reader.addIIOReadWarningListener((source, message) -> warning.set(true));
                var decoded = reader.read(0, readParameters);
                if (decoded == null || warning.get()) {
                    throw new InvalidContent();
                }
                decoded.flush();
            } catch (IOException | IllegalArgumentException malformed) {
                throw new InvalidContent();
            } finally {
                reader.dispose();
            }
        }
    }

    private static void verifyPdf(Path file) throws IOException {
        try (var source = new RandomAccessReadBufferedFile(file)) {
            try (var pdf = new PDFParser(source).parse(false)) {
                pdf.getDocumentCatalog().getPages();
            } catch (IOException | IllegalArgumentException malformed) {
                throw new InvalidContent();
            }
        }
    }

    public record VerifiedContent(long sizeBytes, String contentType) {}

    public static final class InvalidContent extends RuntimeException {
        private InvalidContent() {
            super("FILE_CONTENT_INVALID");
        }
    }
}
