package io.github.iy88.project1.maintenance;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class SeedManifestTests {
    @TempDir
    Path temporary;

    @Test
    void keepsTheIncompleteFlagUntilTheCallerHasValidatedAndWritesPrivateAtomically() throws Exception {
        Path env = temporary.resolve(".env.dev");
        Files.writeString(env, """
                APP_ENV=test
                DATABASE_URL=jdbc:postgresql://127.0.0.1:5432/project1_seed
                DATABASE_USERNAME=project1_seed
                DATABASE_PASSWORD=test-app-password
                DATABASE_OWNER_USERNAME=project1_seed_owner
                DATABASE_OWNER_PASSWORD=test-owner-password
                REDIS_NAMESPACE=project1:seed:test
                OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
                OSS_REGION=cn-hangzhou
                OSS_BUCKET=seed-test-bucket
                OSS_PREFIX=project1/seed
                OSS_ACCESS_KEY_ID=test-key-id
                OSS_ACCESS_KEY_SECRET=test-key-secret
                CONFIG_VERSION=s1-v1
                """);
        Path manifestPath = temporary.resolve("manifest.json");
        var options = MaintenanceCli.Options.parse(new String[]{
                "seed", "load", "--env-file", env.toString(), "--prepare-reset",
                "--manifest", manifestPath.toString()
        });
        var context = SeedContext.create(new MaintenanceConfig(env), options, "load");
        var outcome = new SeedOutcome();
        outcome.managerId = 1;
        outcome.managerEmail = context.managerEmail();
        outcome.accounts.add(new SeedOutcome.AccountRef(2, "user", "user@example.test", "用户", "user"));
        outcome.productIds.add(10L);
        outcome.browseProductIds.add(10L);
        outcome.categoryIds.add(3L);
        outcome.conversationIds.add(4L);
        outcome.searchTerms.add("台灯");

        var manifest = new SeedManifest(context, outcome);
        manifest.writeIncomplete();
        String incomplete = Files.readString(manifestPath);
        assertThat(incomplete).contains("\"version\": 3");
        assertThat(incomplete).contains("\"complete\": false");
        assertThat(incomplete).contains("\"run_id\": \"" + context.runId() + "\"");
        assertThat(incomplete).doesNotContain("test-key-secret");
        if (FileSystemSupports.posix(manifestPath)) {
            Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(manifestPath);
            assertThat(permissions).containsExactlyInAnyOrder(
                    PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE);
        }

        manifest.markComplete();
        assertThat(Files.readString(manifestPath)).contains("\"complete\": true");
    }

    private static final class FileSystemSupports {
        private static boolean posix(Path path) {
            return path.getFileSystem().supportedFileAttributeViews().contains("posix");
        }
    }
}
