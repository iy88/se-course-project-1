package io.github.iy88.project1.api.file;

import com.aliyun.sdk.service.oss2.credentials.Credentials;
import io.github.iy88.project1.account.persistence.Account;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductService;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.application.FileUpload;
import io.github.iy88.project1.storage.application.FileVerification;
import io.github.iy88.project1.storage.content.FileContentVerifier.InvalidContent;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.FileRulesProperties;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/files")
@Profile("infrastructure")
class FileController {
    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";

    private final CurrentAccount current;
    private final FileUpload uploads;
    private final FileRegistry registry;
    private final FileVerification verification;
    private final FileRulesProperties rules;
    private final ProductService products;
    private final String endpoint;
    private final String region;
    private final String bucket;
    private final String prefix;
    private final Credentials credentials;

    FileController(CurrentAccount current, FileUpload uploads, FileRegistry registry,
                   FileVerification verification, FileRulesProperties rules, ProductService products,
                   Environment environment) {
        this.current = current;
        this.uploads = uploads;
        this.registry = registry;
        this.verification = verification;
        this.rules = rules;
        this.products = products;
        endpoint = environment.getRequiredProperty("OSS_ENDPOINT");
        region = environment.getRequiredProperty("OSS_REGION");
        bucket = environment.getRequiredProperty("OSS_BUCKET");
        prefix = environment.getRequiredProperty("OSS_PREFIX");
        credentials = new Credentials(environment.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
    }

    @GetMapping("/upload-capabilities")
    ResponseEntity<Capabilities> capabilities(HttpServletRequest request) {
        current.require(request);
        Map<String, Limits> purposes = new LinkedHashMap<>();
        purposes.put(FilePurpose.PRODUCT_IMAGE.value(), limits(rules.productImage()));
        purposes.put(FilePurpose.CASE_EVIDENCE.value(), limits(rules.caseEvidence()));
        purposes.put(FilePurpose.ACCOUNT_AVATAR.value(), limits(rules.productImage()));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(new Capabilities(rules.ruleVersion(), purposes, rules.uploadTtlSeconds(),
                        rules.readUrlTtlSeconds()));
    }

    @PostMapping("/uploads")
    ResponseEntity<UploadResponse> authorize(@RequestBody UploadRequest body, HttpServletRequest request) {
        requireIdempotencyKey(request);
        Account account = current.require(request).account();
        FilePurpose purpose;
        try {
            purpose = FilePurpose.fromValue(body.purpose());
        } catch (RuntimeException invalid) {
            throw new BusinessError("INPUT_INVALID", 422, "文件用途无效");
        }
        UploadRegistration.Target target = target(account.id(), purpose, body.target());
        var purposeRules = rules.rulesFor(purpose);
        if (body.declaredSize() == null || body.declaredSize() <= 0
                || body.declaredSize() > purposeRules.maxBytes()
                || body.declaredContentType() == null
                || !purposeRules.allowedContentTypes().contains(body.declaredContentType())) {
            throw new BusinessError("FILE_METADATA_INVALID", 422, "文件大小或类型不符合用途限制");
        }
        return storage(() -> withOss(objects -> {
            var draft = uploads.prepare(account.id(), purpose, target, objects.newLocation(purpose),
                    body.declaredSize(), body.declaredContentType(), "account-file-api");
            var form = objects.signUpload(draft.location(), region, credentials, draft.createdAt(),
                    draft.expiresAt(), draft.declaredSize(), draft.declaredContentType());
            var entry = registry.register(draft);
            return ResponseEntity.status(201).cacheControl(CacheControl.noStore())
                    .body(new UploadResponse(Long.toString(entry.fileId()), "uploading", entry.upload().expiresAt(),
                            new Upload("POST", form.url(), form.fields()),
                            limits(purposeRules)));
        }));
    }

    @PostMapping("/{fileId}/completion")
    ResponseEntity<CompletionResponse> complete(@PathVariable String fileId, HttpServletRequest request) {
        requireIdempotencyKey(request);
        Account account = current.require(request).account();
        long id = identifier(fileId);
        return storage(() -> withOss(objects -> {
            var entry = verification.verify(id, account.id(), objects, ignored -> { });
            return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                    .body(new CompletionResponse(Long.toString(entry.fileId()),
                            entry.upload().purpose().value(), entry.state(), entry.verifiedAt(),
                            new Metadata(entry.content().sizeBytes(), entry.content().contentType())));
        }));
    }

    private UploadRegistration.Target target(long accountId, FilePurpose purpose, TargetInput input) {
        if (purpose == FilePurpose.ACCOUNT_AVATAR) {
            if (input != null) {
                throw new BusinessError("INPUT_INVALID", 422, "头像上传由服务端确定目标");
            }
            return new UploadRegistration.Target("account", accountId);
        }
        if (purpose == FilePurpose.CASE_EVIDENCE) {
            if (input != null) {
                throw new BusinessError("FILE_ACTION_NOT_ALLOWED", 403, "事项证据暂未开放");
            }
            return null;
        }
        if (input == null) {
            return null;
        }
        if (!"product".equals(input.resourceType())) {
            throw new BusinessError("FILE_PURPOSE_MISMATCH", 422, "目标类型不符");
        }
        long productId = identifier(input.resourceId());
        if (!products.ownsProduct(accountId, productId)) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        return new UploadRegistration.Target("product", productId);
    }

    private static void requireIdempotencyKey(HttpServletRequest request) {
        String key = request.getHeader(IDEMPOTENCY_HEADER);
        if (key == null || key.isBlank()) {
            throw new BusinessError("INPUT_INVALID", 422, "缺少 Idempotency-Key");
        }
    }

    private <T> T withOss(Function<OssFileObjects, T> action) {
        return OssClients.use(endpoint, region, credentials.accessKeyId(), credentials.accessKeySecret(),
                client -> action.apply(new OssFileObjects(client, bucket, prefix)));
    }

    private static <T> T storage(ThrowingSupplier<T> action) {
        try {
            return action.get();
        } catch (FileRegistry.Rejected rejected) {
            throw fileError(rejected.getMessage());
        } catch (InvalidContent invalid) {
            throw new BusinessError("FILE_CONTENT_INVALID", 422, "文件内容无效");
        } catch (OssFileObjects.Failure failure) {
            throw switch (failure.reason()) {
                case CONTENT_CHANGED -> new BusinessError("FILE_CONTENT_CHANGED", 409, "文件内容已变化");
                case OBJECT_MISSING -> new BusinessError("FILE_UPLOAD_INCOMPLETE", 409, "文件尚未上传");
                case INVALID_CONFIGURATION -> new BusinessError("STORAGE_CONFIGURATION_INVALID", 503,
                        "存储配置无效");
                case UNAVAILABLE -> new BusinessError("STORAGE_UNAVAILABLE", 503, "存储暂不可用");
            };
        } catch (IllegalArgumentException invalid) {
            throw new BusinessError("INPUT_INVALID", 422, "文件参数无效");
        }
    }

    private static BusinessError fileError(String code) {
        return switch (code) {
            case "RESOURCE_NOT_VISIBLE" -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "文件不存在");
            case "UPLOAD_AUTH_EXPIRED" -> new BusinessError("UPLOAD_AUTH_EXPIRED", 409, "上传授权已过期");
            case "FILE_UPLOAD_INCOMPLETE" -> new BusinessError("FILE_UPLOAD_INCOMPLETE", 409, "文件尚未上传");
            case "FILE_CONTENT_INVALID" -> new BusinessError("FILE_CONTENT_INVALID", 422, "文件内容无效");
            case "FILE_CONTENT_CHANGED" -> new BusinessError("FILE_CONTENT_CHANGED", 409, "文件内容已变化");
            case "FILE_NOT_REFERENCEABLE" -> new BusinessError("FILE_NOT_REFERENCEABLE", 409, "文件不可引用");
            case "FILE_PURPOSE_MISMATCH" -> new BusinessError("FILE_PURPOSE_MISMATCH", 422, "文件用途不符");
            default -> new BusinessError("FILE_NOT_REFERENCEABLE", 409, "文件不可用");
        };
    }

    private static long identifier(String value) {
        try {
            long id = Long.parseLong(value);
            if (id > 0) {
                return id;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the shared invalid identifier error.
        }
        throw new BusinessError("INPUT_INVALID", 422, "标识无效");
    }

    private static Limits limits(FileRulesProperties.Limits limits) {
        return new Limits(limits.maxBytes(), limits.allowedContentTypes());
    }

    private static Limits limits(UploadRegistration.Rules rules) {
        return new Limits(rules.maxBytes(), rules.allowedContentTypes());
    }

    @FunctionalInterface
    private interface ThrowingSupplier<T> {
        T get();
    }

    record TargetInput(String resourceType, String resourceId) {
    }

    record UploadRequest(String purpose, Long declaredSize, String declaredContentType, TargetInput target) {
    }

    record Upload(String method, URI url, Map<String, String> fields) {
    }

    record Limits(long maxBytes, Set<String> allowedContentTypes) {
    }

    record UploadResponse(String fileId, String state, Instant expiresAt, Upload upload, Limits limits) {
    }

    record Metadata(long sizeBytes, String contentType) {
    }

    record CompletionResponse(String fileId, String purpose, String state, Instant verifiedAt, Metadata metadata) {
    }

    record Capabilities(String ruleVersion, Map<String, Limits> purposes, int uploadTtlSeconds,
                        int readUrlTtlSeconds) {
    }
}
