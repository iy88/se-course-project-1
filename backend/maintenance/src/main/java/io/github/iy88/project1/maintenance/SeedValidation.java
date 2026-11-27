package io.github.iy88.project1.maintenance;

import java.sql.SQLException;
import java.util.HashSet;
import java.util.Set;

/** Post-commit checks. A manifest may become complete only after every check here passes. */
final class SeedValidation {
    private SeedValidation() {
    }

    static void validate(SeedContext context, SeedDatabase database, SeedOutcome outcome,
                         SeedFiles files) throws SQLException {
        long accounts = database.queryLong("select count(*) from account");
        if (accounts != outcome.accounts.size() + 1L) {
            throw new IllegalStateException("Account count does not match the seeded manifest");
        }
        if (database.queryLong("""
                select count(*) from account
                 where account_id = ? and role = 'manager' and email = ?
                """, outcome.managerId, outcome.managerEmail) != 1) {
            throw new IllegalStateException("Seeded manager account does not match the manifest");
        }
        Set<Long> accountIds = new HashSet<>();
        for (var account : outcome.accounts) {
            if (!accountIds.add(account.id())) {
                throw new IllegalStateException("Duplicate seeded account ID in manifest");
            }
            long matches = database.queryLong("""
                    select count(*) from account
                     where account_id = ? and email = ? and display_name = ? and role = ?
                    """, account.id(), account.email(), account.displayName(), account.role());
            if (matches != 1) {
                throw new IllegalStateException("Seeded account does not match the manifest: " + account.alias());
            }
        }
        long products = database.queryLong("select count(*) from product where deleted_at is null");
        if (products != outcome.productIds.size()) {
            throw new IllegalStateException("Product count does not match the seeded manifest");
        }
        for (long category : outcome.categoryIds) {
            if (database.queryLong("select count(*) from category where category_id = ?", category) != 1) {
                throw new IllegalStateException("A seeded category is missing");
            }
        }
        long images = database.queryLong("""
                select count(*) from product p
                 where p.deleted_at is null
                   and exists (select 1 from file_reference f
                                join file_record r on r.file_id = f.file_id
                               where f.target_type = 'product' and f.target_id = p.product_id
                                 and f.slot = 'image' and r.state = 'verified')
                """);
        if (images != outcome.productIds.size()) {
            throw new IllegalStateException("Every seeded product must reference a verified product image");
        }
        long verified = database.queryLong("""
                select count(*) from file_record
                 where state = 'verified' and verified_size = declared_size
                   and verified_content_type = declared_content_type
                   and content_etag is not null
                """);
        if (verified != outcome.uploadedFiles.size()) {
            throw new IllegalStateException("Verified file records do not match uploaded seed files");
        }
        for (var file : outcome.uploadedFiles) {
            long matches = database.queryLong("""
                    select count(*) from file_record
                     where bucket = ? and object_key = ? and state = 'verified' and verified_size = ?
                       and verified_content_type = ? and content_etag = ?
                       and exists (select 1 from file_reference r where r.file_id = file_record.file_id)
                    """, context.bucket(), file.objectKey(), (long) file.sizeBytes(),
                    file.asset().contentType(), file.eTag());
            if (matches != 1) {
                throw new IllegalStateException("Seeded file metadata is incomplete: " + file.asset().name());
            }
        }
        long conversations = database.queryLong("select count(*) from chat_conversation");
        if (conversations != outcome.conversationIds.size()) {
            throw new IllegalStateException("Chat conversation count does not match the seeded manifest");
        }
        for (long conversation : outcome.conversationIds) {
            if (database.queryLong("select count(*) from chat_conversation where chat_conversation_id = ?",
                    conversation) != 1) {
                throw new IllegalStateException("A seeded chat conversation is missing");
            }
        }
        Set<Long> productIds = new HashSet<>(outcome.productIds);
        Set<Long> browseIds = new HashSet<>(outcome.browseProductIds);
        for (var pair : outcome.tradePairs) {
            if (!accountIds.contains(pair.user()) || !accountIds.contains(pair.peer())
                    || pair.user() == pair.peer() || !productIds.contains(pair.productId())
                    || browseIds.contains(pair.productId())) {
                throw new IllegalStateException("A trade fixture does not match the seeded accounts and pools");
            }
        }
        for (var pair : outcome.tradePairs) {
            long state = database.queryLong("""
                    select count(*) from product
                     where product_id = ? and deleted_at is null
                    """, pair.productId());
            if (state != 1) {
                throw new IllegalStateException("A seeded trade product is missing");
            }
        }
        for (long product : outcome.browseProductIds) {
            long visible = database.queryLong("""
                    select count(*) from product
                     where product_id = ? and lifecycle_state = 'public' and deleted_at is null
                       and not exists (select 1 from product_display_restriction r
                                        where r.product_id = product.product_id and r.released_at is null)
                    """, product);
            if (visible != 1) {
                throw new IllegalStateException("A browse pool product is not publicly visible");
            }
        }
        Set<String> scenarioKeys = new HashSet<>();
        for (var scenario : outcome.scenarios) {
            if (!scenarioKeys.add(scenario.key())) {
                throw new IllegalStateException("Duplicate seeded scenario key: " + scenario.key());
            }
            long matches = switch (scenario.kind()) {
                case "account" -> database.queryLong(
                        "select count(*) from account where account_id = ?", scenario.id());
                case "product" -> database.queryLong(
                        "select count(*) from product where product_id = ? and deleted_at is null", scenario.id());
                case "trade" -> database.queryLong(
                        "select count(*) from trade where id = ?", scenario.id());
                case "chat" -> database.queryLong(
                        "select count(*) from chat_conversation where chat_conversation_id = ?", scenario.id());
                case "trade_conversation" -> database.queryLong(
                        "select count(*) from trade_conversation where trade_conversation_id = ?", scenario.id());
                case "case_conversation" -> database.queryLong(
                        "select count(*) from case_conversation where case_conversation_id = ?", scenario.id());
                case "case" -> database.queryLong(
                        "select count(*) from moderation_case where id = ?", scenario.id());
                case "report_case" -> database.queryLong(
                        "select count(*) from moderation_case where id = ? and case_type = 'report'", scenario.id());
                default -> throw new IllegalStateException("Unknown seeded scenario kind: " + scenario.kind());
            };
            if (matches != 1) {
                throw new IllegalStateException("Seeded scenario is not complete: " + scenario.key());
            }
        }
        files.verifySamples(outcome.uploadedFiles, 3);
    }
}
