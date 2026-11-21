package io.github.iy88.project1.dev.fileprobe;

import com.aliyun.sdk.service.oss2.credentials.Credentials;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.application.FileUpload;
import io.github.iy88.project1.storage.application.FileVerification;
import io.github.iy88.project1.storage.content.FileContentVerifier.InvalidContent;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.FileRulesProperties;
import io.github.iy88.project1.storage.persistence.UploadRegistration.Target;
import jakarta.persistence.EntityManager;
import jakarta.persistence.Tuple;
import java.net.URI;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("file-probe & infrastructure & !dependency-probe")
@RequestMapping(path = "/__dev/file-probe", headers = "X-File-Probe=1", produces = MediaType.APPLICATION_JSON_VALUE)
public class FileProbeController {
    private static final String SLOT = "file";
    private final long account = new SecureRandom().nextLong(1, Long.MAX_VALUE);
    private final Target target = new Target("dev_file_probe", account);
    private final FileUpload upload;
    private final FileVerification verification;
    private final FileRead read;
    private final FileRegistry registry;
    private final FileReferences references;
    private final FileRulesProperties rules;
    private final TransactionTemplate transaction;
    private final EntityManager entities;
    private final String endpoint;
    private final String region;
    private final String bucket;
    private final String prefix;
    private final Credentials credentials;

    public FileProbeController(Environment env, FileUpload upload, FileVerification verification, FileRead read,
                        FileRegistry registry, FileReferences references, FileRulesProperties rules,
                        TransactionTemplate transaction, EntityManager entities) {
        if (!"dev".equals(env.getProperty("APP_ENV"))
                || !"127.0.0.1".equals(env.getProperty("server.address", env.getProperty("HTTP_BIND_HOST")))) {
            throw new IllegalArgumentException("file-probe requires APP_ENV=dev and server.address=127.0.0.1");
        }
        this.upload = upload;
        this.verification = verification;
        this.read = read;
        this.registry = registry;
        this.references = references;
        this.rules = rules;
        this.transaction = transaction;
        this.entities = entities;
        endpoint = env.getRequiredProperty("OSS_ENDPOINT");
        region = env.getRequiredProperty("OSS_REGION");
        bucket = env.getRequiredProperty("OSS_BUCKET");
        prefix = env.getRequiredProperty("OSS_PREFIX");
        credentials = new Credentials(env.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                env.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
    }

    @GetMapping("/limits")
    public ResponseEntity<Map<String, FileRulesProperties.Limits>> limits() {
        return respond(HttpStatus.OK, Map.of(FilePurpose.PRODUCT_IMAGE.value(), rules.productImage(),
                FilePurpose.CASE_EVIDENCE.value(), rules.caseEvidence()));
    }

    @GetMapping("/uploads")
    public ResponseEntity<List<ListedFile>> list() {
        var rows = entities.createQuery("""
                select f.id as fileId, f.purpose as purpose, f.state as state, r.id as referenceId
                from FileRecord f left join FileReference r
                    on r.fileId = f.id and r.targetType = :type and r.targetId = :targetId and r.slot = :slot
                where f.ownerAccountId = :account and f.targetType = :type and f.targetId = :targetId
                order by f.id desc
                """, Tuple.class)
                .setParameter("account", account)
                .setParameter("type", target.type())
                .setParameter("targetId", target.id())
                .setParameter("slot", SLOT)
                .getResultList()
                .stream()
                .map(row -> new ListedFile(row.get("fileId", Long.class).toString(), row.get("purpose", String.class),
                        row.get("state", String.class), row.get("referenceId", Long.class)))
                .toList();
        return respond(HttpStatus.OK, rows);
    }

    @PostMapping(path = "/uploads", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<UploadResponse> authorize(@RequestBody UploadInput input) {
        if (input.purpose() == null) {
            throw new IllegalArgumentException("Missing purpose");
        }
        var purpose = FilePurpose.fromValue(input.purpose());
        var result = withOss(objects -> {
            var draft = upload.prepare(account, purpose, target, objects.newLocation(purpose),
                    input.size(), input.contentType(), "dev-file-probe");
            var form = objects.signUpload(draft.location(), region, credentials, draft.createdAt(), draft.expiresAt(),
                    draft.declaredSize(), draft.declaredContentType());
            var entry = registry.register(draft);
            return new UploadResponse(Long.toString(entry.fileId()), entry.upload().expiresAt(), form);
        });
        return respond(HttpStatus.CREATED, result);
    }

    @PostMapping("/uploads/{fileId}/complete")
    public ResponseEntity<Completed> complete(@PathVariable long fileId) {
        var entry = withOss(objects -> verification.verify(fileId, account, objects, this::requireProbeFile));
        var reference = transaction.execute(status -> references.attach(account, target, entry.upload().purpose(),
                List.of(fileId), SLOT).getFirst());
        return respond(HttpStatus.OK, new Completed(Long.toString(reference.referenceId()), entry.verifiedAt()));
    }

    @GetMapping("/uploads/{fileId}/read")
    public ResponseEntity<ReadResponse> read(@PathVariable long fileId) {
        var result = withOss(objects -> read.prepare(target, fileId, objects,
                () -> requireProbeFile(registry.getOwned(fileId, account))));
        return respond(HttpStatus.OK, new ReadResponse(result.url(), result.expiresAt()));
    }

    @PostMapping("/references/{referenceId}/release")
    public ResponseEntity<Void> release(@PathVariable long referenceId) {
        var basis = new FileReferences.RetentionBasis("dev.file_probe.release", Set.of("TC-COM-007"),
                null, Set.of());
        transaction.executeWithoutResult(status -> references.release(target, List.of(referenceId), basis));
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    private void requireProbeFile(FileRegistry.Entry entry) {
        if (!target.equals(entry.upload().target())) {
            throw new FileRegistry.Rejected("RESOURCE_NOT_VISIBLE");
        }
    }

    private <T> T withOss(Function<OssFileObjects, T> action) {
        return OssClients.use(endpoint, region, credentials.accessKeyId(), credentials.accessKeySecret(),
                client -> action.apply(new OssFileObjects(client, bucket, prefix)));
    }

    @ExceptionHandler(FileRegistry.Rejected.class)
    public ResponseEntity<ErrorCode> rejected(FileRegistry.Rejected failure) {
        var status = "RESOURCE_NOT_VISIBLE".equals(failure.getMessage()) ? HttpStatus.NOT_FOUND : HttpStatus.CONFLICT;
        return respond(status, new ErrorCode(failure.getMessage()));
    }

    @ExceptionHandler(InvalidContent.class)
    public ResponseEntity<ErrorCode> invalidContent() {
        return respond(HttpStatus.UNPROCESSABLE_CONTENT, new ErrorCode("FILE_CONTENT_INVALID"));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ErrorCode> invalidInput() {
        return respond(HttpStatus.BAD_REQUEST, new ErrorCode("INPUT_INVALID"));
    }

    @ExceptionHandler(OssFileObjects.Failure.class)
    public ResponseEntity<ErrorCode> storageFailure(OssFileObjects.Failure failure) {
        return switch (failure.reason()) {
            case CONTENT_CHANGED -> respond(HttpStatus.CONFLICT, new ErrorCode("FILE_CONTENT_CHANGED"));
            case OBJECT_MISSING -> respond(HttpStatus.CONFLICT, new ErrorCode("FILE_UPLOAD_INCOMPLETE"));
            case INVALID_CONFIGURATION -> respond(HttpStatus.SERVICE_UNAVAILABLE,
                    new ErrorCode("STORAGE_CONFIGURATION_INVALID"));
            case UNAVAILABLE -> respond(HttpStatus.SERVICE_UNAVAILABLE, new ErrorCode("STORAGE_UNAVAILABLE"));
        };
    }

    private static <T> ResponseEntity<T> respond(HttpStatus status, T body) {
        return ResponseEntity.status(status).cacheControl(CacheControl.noStore()).body(body);
    }

    public record ListedFile(String fileId, String purpose, String state, String referenceId) {
        ListedFile(String fileId, String purpose, String state, Long referenceId) {
            this(fileId, purpose, state, referenceId == null ? null : referenceId.toString());
        }
    }

    public record UploadInput(String purpose, long size, String contentType) {}
    public record UploadResponse(String fileId, Instant expiresAt, OssFileObjects.UploadForm upload) {}
    public record Completed(String referenceId, Instant verifiedAt) {}
    public record ReadResponse(URI url, Instant expiresAt) {}
    public record ErrorCode(String code) {}
}
