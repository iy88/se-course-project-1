package io.github.iy88.project1.account.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.application.FileRead;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Service
@Profile("infrastructure")
public class AccountAvatarService {
    private final FileReferences references;
    private final FileRead reads;
    private final Settings oss;

    public AccountAvatarService(FileReferences references, FileRead reads, Environment environment) {
        this.references = references;
        this.reads = reads;
        this.oss = new Settings(environment.getRequiredProperty("OSS_ENDPOINT"),
                environment.getRequiredProperty("OSS_REGION"), environment.getRequiredProperty("OSS_BUCKET"),
                environment.getRequiredProperty("OSS_PREFIX"), environment.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
    }

    public String currentUrl(long accountId) {
        var target = new UploadRegistration.Target("account", accountId);
        var current = references.current(target, "avatar");
        if (current.isEmpty()) {
            return null;
        }
        boolean transactional = TransactionSynchronizationManager.isActualTransactionActive();
        var read = OssClients.use(oss.endpoint(), oss.region(), oss.accessKeyId(), oss.accessKeySecret(),
                client -> {
                    var objects = new OssFileObjects(client, oss.bucket(), oss.prefix());
                    long fileId = current.getFirst().fileId();
                    return transactional
                            ? reads.signInReadSnapshot(target, fileId, objects)
                            : reads.prepare(target, fileId, objects, () -> { });
                });
        return read.url().toString();
    }

    /** Signs the current avatar of every account that has one; missing avatars are omitted. */
    public Map<Long, String> currentUrls(Collection<Long> accountIds) {
        if (accountIds.isEmpty()) {
            return Map.of();
        }
        boolean transactional = TransactionSynchronizationManager.isActualTransactionActive();
        Map<Long, String> urls = new LinkedHashMap<>();
        OssClients.use(oss.endpoint(), oss.region(), oss.accessKeyId(), oss.accessKeySecret(), client -> {
            var objects = new OssFileObjects(client, oss.bucket(), oss.prefix());
            for (long accountId : accountIds) {
                var target = new UploadRegistration.Target("account", accountId);
                var current = references.current(target, "avatar");
                if (current.isEmpty()) {
                    continue;
                }
                var read = transactional
                        ? reads.signInReadSnapshot(target, current.getFirst().fileId(), objects)
                        : reads.prepare(target, current.getFirst().fileId(), objects, () -> { });
                urls.put(accountId, read.url().toString());
            }
            return null;
        });
        return Map.copyOf(urls);
    }

    /** Must run inside the account write transaction. */
    public void replace(long accountId, long fileId) {
        var target = new UploadRegistration.Target("account", accountId);
        releaseCurrent(target);
        try {
            references.attach(accountId, target, FilePurpose.ACCOUNT_AVATAR, List.of(fileId), "avatar");
        } catch (FileRegistry.Rejected rejected) {
            throw fileError(rejected.getMessage());
        }
    }

    /** Must run inside the account write transaction. */
    public void remove(long accountId) {
        releaseCurrent(new UploadRegistration.Target("account", accountId));
    }

    private void releaseCurrent(UploadRegistration.Target target) {
        var current = references.current(target, "avatar");
        if (!current.isEmpty()) {
            references.release(target, current.stream().map(FileReferences.Reference::referenceId).toList(),
                    new FileReferences.RetentionBasis("avatar_replaced", Set.of("s2-v1"), null, Set.of()));
        }
    }

    private static BusinessError fileError(String code) {
        return switch (code) {
            case "RESOURCE_NOT_VISIBLE" -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "文件不存在");
            case "FILE_PURPOSE_MISMATCH" -> new BusinessError("FILE_PURPOSE_MISMATCH", 422, "文件用途不符");
            case "FILE_NOT_REFERENCEABLE" -> new BusinessError("FILE_NOT_REFERENCEABLE", 409, "文件尚未核验");
            default -> new BusinessError("INPUT_INVALID", 422, "文件不可用");
        };
    }

    private record Settings(String endpoint, String region, String bucket, String prefix, String accessKeyId,
                            String accessKeySecret) {
    }
}
