package io.github.iy88.project1.maintenance;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * Private, run-bound manifest. The complete flag is written only after DB/OSS validation;
 * the first phase leaves complete=false so a failed run can never look usable.
 */
final class SeedManifest {
    private static final Set<PosixFilePermission> PRIVATE = PosixFilePermissions.fromString("rw-------");

    private final SeedContext context;
    private final SeedOutcome outcome;
    private final String generatedAt;

    SeedManifest(SeedContext context, SeedOutcome outcome) {
        this.context = context;
        this.outcome = outcome;
        generatedAt = Instant.now().toString();
    }

    void writeIncomplete() throws IOException {
        write(false);
    }

    void markComplete() throws IOException {
        write(true);
    }

    private void write(boolean complete) throws IOException {
        if (outcome.managerId <= 0) {
            throw new IllegalStateException("Seed outcome has no manager account");
        }
        Path target = context.manifestPath().toAbsolutePath().normalize();
        Files.createDirectories(target.getParent());
        if (!complete && Files.exists(target)) {
            throw new IllegalStateException("Manifest already exists; use a new --manifest path per run");
        }
        Path temporary = target.resolveSibling("." + target.getFileName() + ".tmp-" + UUID.randomUUID());
        try {
            if (Files.getFileStore(target.getParent()).supportsFileAttributeView("posix")) {
                Files.createFile(temporary, PosixFilePermissions.asFileAttribute(PRIVATE));
            } else {
                Files.createFile(temporary);
            }
            Files.writeString(temporary, json(complete), StandardCharsets.UTF_8);
            if (complete) {
                move(temporary, target, true);
            } else {
                move(temporary, target, false);
            }
            privatePermissions(target);
        } finally {
            Files.deleteIfExists(temporary);
        }
    }

    private void move(Path source, Path target, boolean replace) throws IOException {
        try {
            if (replace) {
                Files.move(source, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } else {
                Files.move(source, target, StandardCopyOption.ATOMIC_MOVE);
            }
        } catch (AtomicMoveNotSupportedException unsupported) {
            if (replace) {
                Files.move(source, target, StandardCopyOption.REPLACE_EXISTING);
            } else {
                Files.move(source, target);
            }
        }
    }

    private static void privatePermissions(Path path) {
        try {
            Files.setPosixFilePermissions(path, PRIVATE);
        } catch (UnsupportedOperationException ignored) {
            // Non-POSIX filesystems cannot express 0600; the parent directory remains access controlled.
        } catch (IOException failure) {
            throw new IllegalStateException("Unable to restrict manifest permissions", failure);
        }
    }

    private String json(boolean complete) {
        StringBuilder json = new StringBuilder(1 << 20);
        json.append("{\n");
        field(json, "version", 3, false);
        field(json, "format_version", 3, false);
        field(json, "complete", complete, false);
        field(json, "mode", context.mode(), false);
        field(json, "run_id", context.runId(), false);
        field(json, "tag", context.tag(), false);
        field(json, "generated_at", generatedAt, false);
        field(json, "password", context.password(), false);
        field(json, "users", outcome.accounts.size(), false);
        field(json, "products", outcome.productIds.size(), false);
        json.append("  \"manager\": ").append(accountJson(outcome.managerId, "manager", outcome.managerEmail, "管理员",
                "manager")).append(",\n");
        json.append("  \"accounts\": [");
        for (int index = 0; index < outcome.accounts.size(); index++) {
            if (index > 0) json.append(',');
            var account = outcome.accounts.get(index);
            json.append('\n').append("    ")
                    .append(accountJson(account.id(), account.alias(), account.email(), account.displayName(), account.role()));
        }
        json.append("\n  ],\n");
        numbers(json, "product_ids", outcome.productIds);
        numbers(json, "browse_product_ids", outcome.browseProductIds);
        json.append("  \"trade_pairs\": [");
        for (int index = 0; index < outcome.tradePairs.size(); index++) {
            if (index > 0) json.append(',');
            var pair = outcome.tradePairs.get(index);
            json.append('\n').append("    {\"user\":").append(pair.user())
                    .append(",\"peer\":").append(pair.peer())
                    .append(",\"product_id\":").append(pair.productId())
                    .append(",\"product_version\":").append(pair.productVersion()).append('}');
        }
        json.append("\n  ],\n");
        numbers(json, "category_ids", outcome.categoryIds);
        numbers(json, "conversation_ids", outcome.conversationIds);
        strings(json, "search_terms", outcome.searchTerms);
        json.append("  \"pools\": {\"browse\":").append(outcome.browseProductIds.size())
                .append(",\"trade\":").append(outcome.tradePairs.size())
                .append(",\"trade_products_disjoint\":true},\n");
        List<SeedFiles.UploadedFile> images = outcome.uploadedFiles.stream()
                .filter(file -> "product_image".equals(file.purpose())).toList();
        if (images.isEmpty()) {
            field(json, "image_base64", "", false);
            field(json, "image_sha256", SeedSupport.sha256Hex(new byte[0]), false);
            json.append("  \"image_assets\": [],\n");
        } else {
            var first = images.getFirst();
            field(json, "image_base64", SeedSupport.base64(first.bytes()), false);
            field(json, "image_sha256", first.sha256(), false);
            json.append("  \"image_assets\": [");
            for (int index = 0; index < images.size(); index++) {
                var file = images.get(index);
                if (index > 0) json.append(',');
                json.append('\n').append("    {\"name\":").append(SeedSupport.jsonString(file.asset().name()))
                        .append(",\"sha256\":").append(SeedSupport.jsonString(file.sha256()))
                        .append(",\"size_bytes\":").append(file.sizeBytes())
                        .append(",\"base64\":").append(SeedSupport.jsonString(SeedSupport.base64(file.bytes())))
                        .append('}');
            }
            json.append("\n  ],\n");
        }
        json.append("  \"scenarios\": [");
        for (int index = 0; index < outcome.scenarios.size(); index++) {
            if (index > 0) json.append(',');
            var scenario = outcome.scenarios.get(index);
            json.append('\n').append("    {\"key\":").append(SeedSupport.jsonString(scenario.key()))
                    .append(",\"kind\":").append(SeedSupport.jsonString(scenario.kind()))
                    .append(",\"id\":").append(SeedSupport.jsonString(Long.toString(scenario.id()))).append('}');
        }
        json.append("\n  ],\n");
        json.append("  \"target\": {\"database\":").append(SeedSupport.jsonString(context.config()
                        .postgresUrl("DATABASE_URL").target()))
                .append(",\"oss_bucket\":").append(SeedSupport.jsonString(context.bucket()))
                .append(",\"oss_prefix\":").append(SeedSupport.jsonString(context.prefix()))
                .append(",\"redis_namespace\":").append(SeedSupport.jsonString(context.redisNamespace()))
                .append("}\n");
        json.append("}\n");
        return json.toString();
    }

    private static String accountJson(long id, String alias, String email, String displayName, String role) {
        return "{\"id\":" + SeedSupport.jsonString(Long.toString(id))
                + ",\"alias\":" + SeedSupport.jsonString(alias)
                + ",\"email\":" + SeedSupport.jsonString(email)
                + ",\"display_name\":" + SeedSupport.jsonString(displayName)
                + ",\"role\":" + SeedSupport.jsonString(role) + "}";
    }

    private static void field(StringBuilder json, String name, Object value, boolean quote) {
        json.append("  ").append(SeedSupport.jsonString(name)).append(": ");
        if (value instanceof Boolean bool) {
            json.append(bool);
        } else if (value instanceof Number number) {
            json.append(number);
        } else {
            json.append(SeedSupport.jsonString(value.toString()));
        }
        json.append(",\n");
    }

    private static void numbers(StringBuilder json, String name, List<Long> values) {
        json.append("  ").append(SeedSupport.jsonString(name)).append(": [");
        for (int index = 0; index < values.size(); index++) {
            if (index > 0) json.append(',');
            json.append(values.get(index));
        }
        json.append("],\n");
    }

    private static void strings(StringBuilder json, String name, List<String> values) {
        json.append("  ").append(SeedSupport.jsonString(name)).append(": [");
        for (int index = 0; index < values.size(); index++) {
            if (index > 0) json.append(',');
            json.append(SeedSupport.jsonString(values.get(index)));
        }
        json.append("],\n");
    }
}
