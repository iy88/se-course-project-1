package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.integration.HttpItSupport.Session;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import io.github.iy88.project1.storage.persistence.FileCleanup;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileReferences.RetentionBasis;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.core.env.Environment;

/** Real PostgreSQL coverage for file registration, references, retention and release rules. */
class FileReferenceCoverageIT {
    private static final UUID RUN = UUID.randomUUID();
    private static HttpItSupport http;
    private static Session owner;
    private static Session other;
    private static FileRegistry registry;
    private static FileReferences references;
    private static FileCleanup cleanup;
    private static Environment environment;
    private static TransactionTemplate transactions;
    private static long product;
    private static long otherProduct;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("file-references");
        owner = http.account("file-reference-owner", "user");
        other = http.account("file-reference-other", "user");
        registry = http.app.getBean(FileRegistry.class);
        references = http.app.getBean(FileReferences.class);
        cleanup = http.app.getBean(FileCleanup.class);
        environment = http.app.getEnvironment();
        transactions = new TransactionTemplate(http.app.getBean(PlatformTransactionManager.class));
        product = product(owner, "File reference " + RUN);
        otherProduct = product(owner, "File retained " + RUN);
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void registrationVerificationReferencesAndRetentionAreScoped() {
        var target = new UploadRegistration.Target("product", product);
        var retainedTarget = new UploadRegistration.Target("product", otherProduct);
        var image = register(owner, FilePurpose.PRODUCT_IMAGE, target, "image/png", 8);
        var avatar = register(owner, FilePurpose.ACCOUNT_AVATAR, null, "image/jpeg", 9);
        var unverified = registerRaw(owner, FilePurpose.PRODUCT_IMAGE, target, "image/png", 7);

        assertThatThrownBy(() -> transactions.executeWithoutResult(status -> references.attach(
                http.accountId(owner), target, FilePurpose.PRODUCT_IMAGE, List.of(unverified.fileId()), "images")))
                .hasMessage("FILE_NOT_REFERENCEABLE");
        assertThatThrownBy(() -> transactions.executeWithoutResult(status -> references.attach(
                http.accountId(other), target, FilePurpose.PRODUCT_IMAGE, List.of(image.fileId()), "images")))
                .hasMessage("RESOURCE_NOT_VISIBLE");
        assertThatThrownBy(() -> transactions.executeWithoutResult(status -> references.attach(
                http.accountId(owner), target, FilePurpose.CASE_EVIDENCE, List.of(image.fileId()), "images")))
                .hasMessage("FILE_PURPOSE_MISMATCH");
        assertThatThrownBy(() -> transactions.executeWithoutResult(status -> references.attach(
                http.accountId(owner), target, FilePurpose.PRODUCT_IMAGE, List.of(0L), "images")))
                .hasMessage("File and reference IDs must be positive");

        var attached = transactions.execute(status -> references.attach(http.accountId(owner), target,
                FilePurpose.PRODUCT_IMAGE, List.of(image.fileId()), "images"));
        assertThat(attached).hasSize(1);
        long imageReference = attached.getFirst().referenceId();
        assertThat(references.current(target, "images")).extracting(FileReferences.Reference::fileId)
                .containsExactly(image.fileId());
        assertThat(references.firstCurrent("product", List.of(product, otherProduct), "images"))
                .containsKey(product);
        assertThat(references.referencedContentType(target, image.fileId())).contains("image/png");
        var read = transactions.execute(status -> references.readReferenced(target, image.fileId()));
        assertThat(read.fileId()).isEqualTo(image.fileId());
        assertThat(references.referencedContentType(retainedTarget, image.fileId())).isEmpty();

        var retained = transactions.execute(status -> references.retain(
                Long.toString(http.accountId(owner)), target, retainedTarget, FilePurpose.PRODUCT_IMAGE,
                List.of(image.fileId()), "images"));
        assertThat(retained).hasSize(1);
        assertThat(references.current(retainedTarget, "images")).hasSize(1);
        assertThatThrownBy(() -> transactions.executeWithoutResult(status -> references.retain(
                Long.toString(http.accountId(owner)), new UploadRegistration.Target("product", product + 10_000),
                new UploadRegistration.Target("product", product + 10_001), FilePurpose.PRODUCT_IMAGE,
                List.of(image.fileId()), "other")))
                .hasMessage("RESOURCE_NOT_VISIBLE");

        List<Long> prepared = transactions.execute(
                status -> references.prepareRelease(target, List.of(imageReference)));
        assertThat(prepared).containsExactly(image.fileId());
        assertThatThrownBy(() -> transactions.executeWithoutResult(status -> references.release(
                target, List.of(imageReference), new RetentionBasis("remove_content", Set.of("rule"),
                        retainedTarget, Set.of(new UploadRegistration.Target("product", product + 10_002))))))
                .hasMessage("FILE_RETENTION_REQUIRED");

        var released = transactions.execute(status -> references.release(target, List.of(imageReference),
                new RetentionBasis("remove_content", Set.of("rule"), retainedTarget, Set.of())));
        assertThat(released.affectedFileIds()).containsExactly(image.fileId());
        assertThat(references.current(target, "images")).isEmpty();
        assertThat(references.current(retainedTarget, "images")).hasSize(1);
    }

    @Test
    void fileValidationRulesRejectChangedExpiredAndMismatchedContent() {
        var target = new UploadRegistration.Target("product", product);
        var immutable = registerRaw(owner, FilePurpose.PRODUCT_IMAGE, target, "image/png", 8);
        assertThat(registry.markVerified(immutable.fileId(), http.accountId(owner), "etag-immutable",
                new VerifiedContent(8, "image/png")).state()).isEqualTo("verified");
        assertThat(registry.markVerified(immutable.fileId(), http.accountId(owner), "etag-immutable",
                new VerifiedContent(8, "image/png")).state()).isEqualTo("verified");
        assertThatThrownBy(() -> registry.markVerified(immutable.fileId(), http.accountId(owner), "other",
                new VerifiedContent(8, "image/png")))
                .hasMessage("FILE_CONTENT_CHANGED");

        var wrongSize = registerRaw(owner, FilePurpose.PRODUCT_IMAGE, target, "image/png", 8);
        assertThatThrownBy(() -> registry.markVerified(wrongSize.fileId(), http.accountId(owner), "etag",
                new VerifiedContent(7, "image/png")))
                .hasMessage("FILE_CONTENT_INVALID");
        var wrongType = registerRaw(owner, FilePurpose.PRODUCT_IMAGE, target, "image/png", 8);
        assertThatThrownBy(() -> registry.markVerified(wrongType.fileId(), http.accountId(owner), "etag",
                new VerifiedContent(8, "image/jpeg")))
                .hasMessage("FILE_CONTENT_INVALID");
        var blankEtag = registerRaw(owner, FilePurpose.PRODUCT_IMAGE, target, "image/png", 8);
        assertThatThrownBy(() -> registry.markVerified(blankEtag.fileId(), http.accountId(owner), " ",
                new VerifiedContent(8, "image/png")))
                .hasMessage("FILE_CONTENT_INVALID");
        assertThatThrownBy(() -> registry.markVerified(999_999_999, http.accountId(owner), "etag",
                new VerifiedContent(8, "image/png")))
                .hasMessage("RESOURCE_NOT_VISIBLE");
        assertThatThrownBy(() -> registry.getOwned(immutable.fileId(), http.accountId(other)))
                .hasMessage("RESOURCE_NOT_VISIBLE");
    }

    @Test
    void cleanupDeletesOnlyExpiredUnreferencedFilesAndRecordsFailures() {
        var target = new UploadRegistration.Target("product", product);
        var referenced = registerExpired(FilePurpose.PRODUCT_IMAGE, target);
        http.db.sql("""
                update file_record
                   set state = 'verified',
                       verified_at = created_at + interval '60 seconds',
                       content_etag = 'cleanup-etag',
                       verified_size = declared_size,
                       verified_content_type = declared_content_type
                 where file_id = ?
                """)
                .param(referenced.fileId()).update();
        transactions.executeWithoutResult(status -> references.attach(http.accountId(owner), target,
                FilePurpose.PRODUCT_IMAGE, List.of(referenced.fileId()), "cleanup"));

        var removable = registerExpired(FilePurpose.ACCOUNT_AVATAR, null);
        var failed = registerExpired(FilePurpose.CASE_EVIDENCE, target);
        var objects = mock(OssFileObjects.class);
        when(objects.bucket()).thenReturn(environment.getRequiredProperty("OSS_BUCKET"));
        when(objects.purposePrefix(any(FilePurpose.class))).thenAnswer(invocation ->
                environment.getRequiredProperty("OSS_PREFIX") + "/" + invocation.<FilePurpose>getArgument(0).value() + "/");
        when(objects.delete(any())).thenAnswer(invocation -> {
            Location location = invocation.getArgument(0);
            if (location.key().contains(FilePurpose.CASE_EVIDENCE.value())) {
                var failure = mock(OssFileObjects.Failure.class);
                when(failure.reason()).thenReturn(OssFileObjects.Reason.UNAVAILABLE);
                when(failure.requestId()).thenReturn("cleanup-failed");
                throw failure;
            }
            return "cleanup-" + location.key();
        });

        var result = cleanup.runBatch(objects, 100);
        assertThat(result.deleted()).isGreaterThanOrEqualTo(1);
        assertThat(result.failures()).anySatisfy(attempt -> {
            assertThat(attempt.fileId()).isEqualTo(failed.fileId());
            assertThat(attempt.reason()).isEqualTo(OssFileObjects.Reason.UNAVAILABLE);
        });
        assertThat(registry.getOwned(referenced.fileId(), http.accountId(owner)).state()).isEqualTo("verified");
        assertThat(state(removable.fileId())).isEqualTo("deleted");
        assertThat(state(failed.fileId())).isEqualTo("cleaning");
    }

    private static FileRegistry.Entry register(Session owner, FilePurpose purpose,
                                                UploadRegistration.Target target, String contentType, long size) {
        var entry = registerRaw(owner, purpose, target, contentType, size);
        return registry.markVerified(entry.fileId(), http.accountId(owner), "etag-" + entry.fileId(),
                new VerifiedContent(size, contentType));
    }

    private static FileRegistry.Entry registerRaw(Session owner, FilePurpose purpose,
                                                  UploadRegistration.Target target, String contentType, long size) {
        return registerRaw(owner, purpose, target, contentType, size, Instant.now());
    }

    private static FileRegistry.Entry registerRaw(Session owner, FilePurpose purpose,
                                                  UploadRegistration.Target target, String contentType,
                                                  long size, Instant createdAt) {
        String bucket = environment.getRequiredProperty("OSS_BUCKET");
        String key = environment.getRequiredProperty("OSS_PREFIX") + "/" + purpose.value() + "/" + UUID.randomUUID();
        var draft = new UploadRegistration.Draft(http.accountId(owner), purpose, target,
                new Location(bucket, key), size, contentType, "integration",
                createdAt, createdAt.plusSeconds(300), createdAt.plusSeconds(600));
        return registry.register(draft);
    }

    private static FileRegistry.Entry registerExpired(FilePurpose purpose, UploadRegistration.Target target) {
        return registerRaw(owner, purpose, target, "image/png", 8, Instant.now().minusSeconds(1_200));
    }

    private static String state(long fileId) {
        return http.db.sql("select state from file_record where file_id = ?")
                .param(fileId).query(String.class).single();
    }

    private static long product(Session seller, String title) {
        return http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 1000, 'public') returning product_id
                """).param(http.accountId(seller)).param(title).query(Long.class).single();
    }
}
