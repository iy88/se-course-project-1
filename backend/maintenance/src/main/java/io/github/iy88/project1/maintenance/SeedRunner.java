package io.github.iy88.project1.maintenance;

import java.io.IOException;
import java.nio.file.Files;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;

/** Entry point for seed load/demo: explicit reset gate, empty-target checks, transaction, validation, manifest. */
final class SeedRunner {
    private static final List<String> SEED_ROOT_TABLES = List.of(
            "account", "account_ban", "audit_record", "category", "product", "file_record",
            "trade", "chat_conversation", "trade_conversation", "case_conversation",
            "moderation_case", "notification", "operation_record", "product_display_restriction");

    private SeedRunner() {
    }

    static void run(MaintenanceConfig config, MaintenanceCli.Options options) throws SQLException, IOException {
        String mode = options.command().substring("seed ".length());
        if (!options.prepareReset()) {
            throw new IllegalStateException("""
                    Seed requires --prepare-reset. Before rerunning:
                      1. stop all API, scheduler and worker processes;
                      2. db reset --env-file <file> (preview then --confirm);
                      3. oss reset --env-file <file> --prefix <configured OSS_PREFIX> (preview then --confirm);
                      4. verify REDIS_NAMESPACE:* is clean, then rerun seed with --prepare-reset.
                    The seed itself never deletes a shared bucket, database or Redis keys.""");
        }
        var postgres = new PostgresMaintenance(config);
        var context = SeedContext.create(config, options, mode);
        if (Files.exists(context.manifestPath(), java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalStateException("Manifest already exists; choose a new --manifest path");
        }
        System.out.println("Seed mode: " + mode + " run=" + context.runId());
        System.out.println(postgres.scope());
        System.out.println("OSS bucket=" + context.bucket() + " scope=PREFIX " + context.prefix()
                + "/ (whole-bucket reset is not used)");
        System.out.println("Redis namespace=" + context.redisNamespace() + " (seed writes no Redis keys)");
        var files = new SeedFiles(context);
        try (Connection connection = postgres.openOwner()) {
            var database = new SeedDatabase(connection);
            database.begin();
            SeedOutcome outcome;
            try {
                if (database.queryLong("select case when pg_try_advisory_xact_lock(52066735102254701) "
                        + "then 1 else 0 end") == 0) {
                    throw new IllegalStateException("Another seed is running against the target database");
                }
                requireEmpty(database);
                files.requirePrefixEmpty();
                outcome = "load".equals(mode)
                        ? LoadSeed.seed(context, database, files)
                        : DemoSeed.seed(context, database, files);
                database.commit();
            } catch (SQLException | RuntimeException failure) {
                database.rollback();
                throw failure;
            }
            var manifest = new SeedManifest(context, outcome);
            manifest.writeIncomplete();
            SeedValidation.validate(context, database, outcome, files);
            manifest.markComplete();
            System.out.println("Validated accounts=" + (outcome.accounts.size() + 1)
                    + " products=" + outcome.productIds.size()
                    + " browse=" + outcome.browseProductIds.size()
                    + " trades=" + outcome.tradePairs.size()
                    + " chats=" + outcome.conversationIds.size()
                    + " files=" + outcome.uploadedFiles.size());
            System.out.println("Manifest (0600, complete=true): " + context.manifestPath().toAbsolutePath());
            System.out.println("Credentials are written only to the manifest; no password or key was logged.");
        }
    }

    private static void requireEmpty(SeedDatabase database) throws SQLException {
        for (String table : SEED_ROOT_TABLES) {
            if (database.queryLong("select count(*) from " + table) > 0) {
                throw new IllegalStateException("Target database is not clean; run db reset before seeding. "
                        + "The seed does not truncate or delete business data.");
            }
        }
    }
}
