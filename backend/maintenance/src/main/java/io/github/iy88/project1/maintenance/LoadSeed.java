package io.github.iy88.project1.maintenance;

import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/** Deterministic load fixture: 100 users, 10,000 public products, separate browse/trade pools and chat pairs. */
final class LoadSeed {
    private LoadSeed() {
    }

    static SeedOutcome seed(SeedContext context, SeedDatabase database, SeedFiles files) throws SQLException {
        int users = context.users();
        int products = context.products();
        if (users < 3) {
            throw new IllegalArgumentException("seed load requires at least 3 users");
        }
        if (products <= users) {
            throw new IllegalArgumentException("seed load requires more products than users");
        }
        var now = context.clock().instant();
        var random = SeedSupport.random(context, "load");
        var outcome = new SeedOutcome();

        // OSS writes happen before the DB transaction; a failed DB write is recovered by
        // rerunning the documented prefix reset, never by deleting a shared bucket.
        var uploads = files.uploadAll(SeedSupport.LOAD_IMAGES);
        outcome.uploadedFiles.addAll(uploads);

        var accounts = new SeedAccounts(database, context);
        outcome.managerId = accounts.create(context.managerEmail(), "平台管理员·联调", "manager", now.minusSeconds(90L * 86_400));
        outcome.managerEmail = context.managerEmail();
        for (int index = 0; index < users; index++) {
            String displayName = SeedSupport.displayName(random);
            long id = accounts.create(context.loadEmail(index), displayName, "user",
                    now.minusSeconds((80L + index % 30) * 86_400));
            outcome.accounts.add(new SeedOutcome.AccountRef(id, "u%03d".formatted(index), context.loadEmail(index),
                    displayName, "user"));
        }

        var categoryIds = SeedCategories.create(database, context, outcome.managerId, now, SeedCategories.LOAD);
        outcome.categoryIds.addAll(categoryIds);
        outcome.searchTerms.addAll(SeedSupport.SEARCH_TERMS);

        List<Long> fileIds = new ArrayList<>();
        for (var upload : uploads) {
            fileIds.add(SeedFileRegistry.record(database, upload, outcome.managerId, context.bucket(),
                    "seed-" + context.configVersion(), now));
        }

        Instant submittedBase = now.minusSeconds(30L * 86_400);
        for (int index = 0; index < products; index++) {
            String term = SeedSupport.SEARCH_TERMS.get(index % SeedSupport.SEARCH_TERMS.size());
            String title = SeedSupport.loadTitle(term, index);
            String description = SeedSupport.loadDescription(random, term, index);
            int sellerIndex = index >= products - users ? (index - (products - users) + 1) % users : index % users;
            long sellerId = outcome.accounts.get(sellerIndex).id();
            Instant createdAt = submittedBase.plusSeconds(index * 37L % (30L * 86_400));
            long productId = database.insert("""
                    insert into product (seller_account_id, title, description, price_cents, lifecycle_state,
                        occupied_by_trade_id, content_version, created_at, updated_at, deleted_at)
                    values (?, ?, ?, ?, 'public', null, 1, ?, ?, null)
                    returning product_id
                    """, sellerId, title, description, 1_000L + (index * 137L) % 90_000L, createdAt, createdAt);
            outcome.productIds.add(productId);
            if (index < products - users) {
                outcome.browseProductIds.add(productId);
            }
            List<Long> selectedCategories = new ArrayList<>();
            selectedCategories.add(categoryIds.get(index % categoryIds.size()));
            if (index % 7 == 0) {
                selectedCategories.add(categoryIds.get((index + 2) % categoryIds.size()));
            }
            for (long categoryId : selectedCategories) {
                database.update("""
                        insert into product_category (product_id, category_id, source, created_by_kind,
                            created_by_id, created_at)
                        values (?, ?, 'seller', 'seller', ?, ?)
                        """, productId, categoryId, sellerId, createdAt.plusSeconds(60));
            }
            SeedFileRegistry.attach(database, fileIds.get(index % fileIds.size()), "product", productId,
                    "image", Long.toString(sellerId), createdAt.plusSeconds(60));
            recordPassedReview(database, context, outcome.managerId, productId, title, description,
                    createdAt, index);
        }

        // Keep the shared case identity sequence ahead of the explicit review case IDs.
        database.queryLong("select setval(pg_get_serial_sequence('moderation_case', 'id'), "
                + "(select max(id) from moderation_case), true)");

        // Reserve one product per user for the trade pool; it never appears in browse IDs.
        for (int user = 0; user < users; user++) {
            int peer = (user + 1) % users;
            long productId = outcome.productIds.get(products - users + user);
            outcome.tradePairs.add(new SeedOutcome.TradePair(outcome.accounts.get(user).id(),
                    outcome.accounts.get(peer).id(), productId, 1));
        }

        createChatPairs(context, database, now, random, outcome);
        return outcome;
    }

    private static void recordPassedReview(SeedDatabase database, SeedContext context, long managerId,
                                           long productId, String title, String description, Instant createdAt,
                                           int index) throws SQLException {
        long caseId = database.queryLong("select nextval('product_review_case_seq')");
        database.update("""
                insert into moderation_case (id, case_type, created_at, claimed_manager_id, claimed_at)
                values (?, 'product_review', ?, ?, ?)
                """, caseId, createdAt, managerId, createdAt.plusSeconds(30));
        String reviewedContent = "{\"title\":" + SeedSupport.jsonString(title)
                + ",\"description\":" + SeedSupport.jsonString(description)
                + ",\"price_cents\":" + (1_000L + (index * 137L) % 90_000L) + "}";
        database.update("""
                insert into product_audit (product_id, sequence_no, case_id, status, submitted_at,
                    decided_by_admin_id, decided_at, decision_reason, reviewed_content,
                    reviewed_banned_item_ids)
                values (?, 1, ?, 'passed', ?, ?, ?, null, ?::jsonb, '[]'::jsonb)
                """, productId, caseId, createdAt, managerId, createdAt.plusSeconds(60), reviewedContent);
    }

    private static void createChatPairs(SeedContext context, SeedDatabase database, Instant now, Random random,
                                        SeedOutcome outcome) throws SQLException {
        for (int user = 0; user < context.users(); user++) {
            int peer = (user + 1) % context.users();
            long low = Math.min(outcome.accounts.get(user).id(), outcome.accounts.get(peer).id());
            long high = Math.max(outcome.accounts.get(user).id(), outcome.accounts.get(peer).id());
            Instant createdAt = now.minusSeconds((3L + user % 5) * 86_400);
            long conversationId = database.insert("""
                    insert into chat_conversation (account_low_id, account_high_id, seq_head, created_at)
                    values (?, ?, 2, ?)
                    returning chat_conversation_id
                    """, low, high, createdAt);
            long senderId = outcome.accounts.get(user).id();
            long peerId = outcome.accounts.get(peer).id();
            database.update("""
                    insert into chat_message (chat_conversation_id, seq, sender_account_id, body, created_at)
                    values (?, 1, ?, ?, ?)
                    """, conversationId, senderId, "联调问候 " + (user + 1), createdAt.plusSeconds(60));
            database.update("""
                    insert into chat_message (chat_conversation_id, seq, sender_account_id, body, created_at)
                    values (?, 2, ?, ?, ?)
                    """, conversationId, peerId,
                    "收到，交易和沟通都可以按约定进行 " + (user + 1), createdAt.plusSeconds(120));
            database.update("""
                    insert into chat_read_progress (chat_conversation_id, account_id, last_read_seq, last_read_at)
                    values (?, ?, 2, ?)
                    """, conversationId, senderId, createdAt.plusSeconds(180));
            database.update("""
                    insert into chat_read_progress (chat_conversation_id, account_id, last_read_seq, last_read_at)
                    values (?, ?, 1, ?)
                    """, conversationId, peerId, createdAt.plusSeconds(150));
            outcome.conversationIds.add(conversationId);
            outcome.scenarios.add(new SeedOutcome.ScenarioRef("chat_pair_" + (user + 1), "chat", conversationId));
            // Keep the deterministic RNG in use for future content additions without changing pair order.
            random.nextInt(3);
        }
    }
}
