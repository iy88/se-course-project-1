package io.github.iy88.project1.maintenance;

import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Persistent, coherent campus demo data rendered by the current user and management UI. */
final class DemoSeed {
    private static final List<SeedCategories.Definition> CATEGORIES = List.of(
            new SeedCategories.Definition("数码电子", List.of("电子产品", "数码")),
            new SeedCategories.Definition("教材书籍", List.of("课本")),
            new SeedCategories.Definition("运动户外", List.of("球类")),
            new SeedCategories.Definition("生活家居", List.of("宿舍好物")),
            new SeedCategories.Definition("骑行装备", List.of()));

    private DemoSeed() {
    }

    static SeedOutcome seed(SeedContext context, SeedDatabase database, SeedFiles files) throws SQLException {
        var now = context.clock().instant();
        var outcome = new SeedOutcome();
        var uploads = files.uploadAll(demoAssets());
        outcome.uploadedFiles.addAll(uploads);
        Map<String, SeedFiles.UploadedFile> byAsset = new LinkedHashMap<>();
        uploads.forEach(file -> byAsset.put(file.asset().name(), file));

        var accounts = new SeedAccounts(database, context);
        outcome.managerId = accounts.create(context.managerEmail(), "平台管理员·周明远", "manager",
                now.minusSeconds(120L * 86_400));
        outcome.managerEmail = context.managerEmail();
        Map<String, Long> userIds = new LinkedHashMap<>();
        for (var account : DemoCatalog.ACCOUNTS) {
            long id = accounts.create(context.demoEmail(account.key()), account.displayName(), account.role(),
                    now.minusSeconds(100L * 86_400));
            userIds.put(account.key(), id);
            outcome.accounts.add(new SeedOutcome.AccountRef(id, account.key(), context.demoEmail(account.key()),
                    account.displayName(), account.role()));
            outcome.scenarios.add(new SeedOutcome.ScenarioRef("account_" + account.key(), "account", id));
        }

        var categoryIds = SeedCategories.create(database, context, outcome.managerId, now, CATEGORIES);
        outcome.categoryIds.addAll(categoryIds);
        Map<String, Long> categoryByName = new LinkedHashMap<>();
        for (int index = 0; index < CATEGORIES.size(); index++) {
            categoryByName.put(CATEGORIES.get(index).name(), categoryIds.get(index));
        }
        outcome.searchTerms.addAll(SeedSupport.SEARCH_TERMS);

        Map<String, Long> productIds = new LinkedHashMap<>();
        Map<String, Long> productImageFiles = new LinkedHashMap<>();
        for (var product : DemoCatalog.PRODUCTS) {
            long sellerId = userIds.get(product.seller());
            Instant createdAt = now.minusSeconds((long) (product.daysAgo() * 86_400));
            String lifecycle = switch (product.state()) {
                case "in_trade" -> "in_trade";
                case "off_shelf" -> "off_shelf";
                case "pending_review" -> "pending_review";
                case "review_rejected" -> "review_rejected";
                case "public" -> "public";
                default -> throw new IllegalStateException("Unsupported demo product state");
            };
            long productId = database.insert("""
                    insert into product (seller_account_id, title, description, price_cents, lifecycle_state,
                        occupied_by_trade_id, content_version, created_at, updated_at, deleted_at)
                    values (?, ?, ?, ?, ?, null, 1, ?, ?, null)
                    returning product_id
                    """, sellerId, product.title(), product.description(), product.priceCents(), lifecycle,
                    createdAt, createdAt);
            productIds.put(product.key(), productId);
            outcome.productIds.add(productId);
            if ("public".equals(lifecycle) && !product.restricted()) {
                outcome.browseProductIds.add(productId);
            }
            long categoryId = categoryByName.get(product.category());
            database.update("""
                    insert into product_category (product_id, category_id, source, created_by_kind,
                        created_by_id, created_at)
                    values (?, ?, 'seller', 'seller', ?, ?)
                    """, productId, categoryId, sellerId, createdAt.plusSeconds(30));
            var upload = byAsset.get(product.asset());
            if (upload == null) {
                throw new IllegalStateException("Demo product asset is not packaged: " + product.key());
            }
            long fileId = SeedFileRegistry.record(database, upload, sellerId, context.bucket(),
                    "seed-" + context.configVersion(), now);
            productImageFiles.put(product.key(), fileId);
            SeedFileRegistry.attach(database, fileId, "product", productId, "image", Long.toString(sellerId),
                    createdAt.plusSeconds(60));
            long caseId = recordReview(database, context, outcome.managerId, productId, product, createdAt);
            outcome.scenarios.add(new SeedOutcome.ScenarioRef("product_" + product.key(), "product", productId));
            if (caseId > 0) {
                outcome.scenarios.add(new SeedOutcome.ScenarioRef("case_review_" + product.key(), "case", caseId));
            }
        }

        // Product review cases used explicit IDs from product_review_case_seq. Advance the
        // moderation_case identity sequence before inserting dispute/report cases.
        database.queryLong("select setval(pg_get_serial_sequence('moderation_case', 'id'), "
                + "(select max(id) from moderation_case), true)");

        // A pending category application is part of the same review flow as its product.
        long lampId = productIds.get("lamp_pending");
        long lampSeller = userIds.get("seller");
        database.update("""
                insert into category_application (product_id, submitted_by_account_id, proposed_name, status,
                    resolution, resolved_category_id, created_at)
                values (?, ?, '宿舍照明', 'pending', null, null, ?)
                """, lampId, lampSeller, now.minusSeconds(2L * 86_400));

        var comments = seedComments(database, now, userIds, productIds);
        for (var comment : DemoCatalog.COMMENTS) {
            if (comment.deleted()) {
                Long commentId = comments.byComment().get(comment);
                if (commentId == null) {
                    throw new IllegalStateException("Removed comment fixture was not inserted");
                }
                seedCommentReport(context, database, now, userIds, commentId, comment, outcome);
            }
        }
        seedFavorites(database, now, userIds, productIds);
        seedTrades(context, database, now, userIds, productIds, productImageFiles, outcome);
        seedReportCase(context, database, now, userIds, productIds, outcome);
        seedChats(context, database, now, userIds, outcome);
        return outcome;
    }

    private static List<SeedSupport.SeedAsset> demoAssets() {
        List<SeedSupport.SeedAsset> assets = new ArrayList<>();
        for (var product : DemoCatalog.PRODUCTS) {
            assets.add(new SeedSupport.SeedAsset(product.asset(),
                    io.github.iy88.project1.storage.FilePurpose.PRODUCT_IMAGE));
        }
        assets.addAll(reportAssets());
        return List.copyOf(assets);
    }

    private static List<SeedSupport.SeedAsset> reportAssets() {
        var assets = new ArrayList<>(SeedSupport.DEMO_EVIDENCE);
        assets.add(new SeedSupport.SeedAsset(DemoChatEvidence.NAME,
                io.github.iy88.project1.storage.FilePurpose.CASE_EVIDENCE,
                DemoChatEvidence.render(DemoCatalog.POWERBANK_CHAT, DemoCatalog.ACCOUNTS)));
        return List.copyOf(assets);
    }

    private static long recordReview(SeedDatabase database, SeedContext context, long managerId, long productId,
                                     DemoCatalog.Product product, Instant createdAt) throws SQLException {
        if ("passed".equals(product.review())) {
            return recordAudit(database, productId, product, createdAt, managerId, "passed", null, false);
        }
        if ("pending".equals(product.review())) {
            return recordAudit(database, productId, product, createdAt,
                    product.claimed() ? managerId : null, "pending", null, false);
        }
        if ("rejected".equals(product.review())) {
            return recordAudit(database, productId, product, createdAt, managerId, "rejected",
                    product.reason(), false);
        }
        if ("withdrawn".equals(product.review())) {
            return recordAudit(database, productId, product, createdAt, null, "withdrawn", null, true);
        }
        throw new IllegalStateException("Unsupported demo review result");
    }

    private static long recordAudit(SeedDatabase database, long productId, DemoCatalog.Product product,
                                    Instant createdAt, Long reviewerId, String status, String reason,
                                    boolean withdrawn) throws SQLException {
        long caseId = database.queryLong("select nextval('product_review_case_seq')");
        database.update("""
                insert into moderation_case (id, case_type, created_at, claimed_manager_id, claimed_at, updated_at)
                values (?, 'product_review', ?, ?, ?, ?)
                """, caseId, createdAt, reviewerId, reviewerId == null ? null : createdAt.plusSeconds(30), createdAt);
        String reviewed = "{\"title\":" + SeedSupport.jsonString(product.title())
                + ",\"description\":" + SeedSupport.jsonString(product.description())
                + ",\"price_cents\":" + product.priceCents() + "}";
        Long deciderId = "passed".equals(status) || "rejected".equals(status) ? reviewerId : null;
        Instant decidedAt = deciderId == null ? null : createdAt.plusSeconds(60);
        database.update("""
                insert into product_audit (product_id, sequence_no, case_id, status, submitted_at,
                    decided_by_admin_id, decided_at, decision_reason, reviewed_content,
                    reviewed_banned_item_ids, withdrawn_at)
                values (?, 1, ?, ?, ?, ?, ?, ?, ?::jsonb, '[]'::jsonb, ?)
                """, productId, caseId, status, createdAt, deciderId, decidedAt, reason, reviewed,
                withdrawn ? createdAt.plusSeconds(60) : null);
        return caseId;
    }

    private record SeededComments(Map<String, Long> byKey, Map<DemoCatalog.Comment, Long> byComment) {
    }

    private static SeededComments seedComments(SeedDatabase database, Instant now, Map<String, Long> users,
                                               Map<String, Long> productIds) throws SQLException {
        Map<String, Long> commentIds = new LinkedHashMap<>();
        Map<DemoCatalog.Comment, Long> commentIdsByDefinition = new LinkedHashMap<>();
        Map<String, Integer> localCounts = new LinkedHashMap<>();
        for (var comment : DemoCatalog.COMMENTS) {
            long productId = productIds.get(comment.product());
            long authorId = users.get(comment.author());
            Instant createdAt = now.minusSeconds((long) (comment.daysAgo() * 86_400));
            Long parentId = comment.replyTo() == null ? null : commentIds.get(comment.replyTo());
            int local = localCounts.merge(comment.product(), 1, (count, increment) -> count + increment);
            long commentId = database.insert("""
                    insert into product_comment (product_id, author_account_id, parent_comment_id, body,
                        created_at, deleted_at, removed_at, removed_by_admin_id, removed_reason, basis_ref)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    returning comment_id
                    """, productId, authorId, parentId, comment.body(), createdAt, null, null, null, null, null);
            commentIds.put(comment.product() + "#" + local, commentId);
            commentIdsByDefinition.put(comment, commentId);
        }
        return new SeededComments(Map.copyOf(commentIds), Map.copyOf(commentIdsByDefinition));
    }

    private static void seedCommentReport(SeedContext context, SeedDatabase database, Instant now,
                                          Map<String, Long> users, long commentId,
                                          DemoCatalog.Comment comment, SeedOutcome outcome) throws SQLException {
        long authorId = users.get(comment.author());
        long reporterId = users.get("outsider");
        if (authorId == reporterId) {
            reporterId = users.get("buyer3");
        }
        long managerId = outcome.managerId;
        Instant createdAt = now.minusSeconds((long) (comment.daysAgo() * 86_400));
        Instant reportedAt = createdAt.plusSeconds(3_600);
        Instant claimedAt = reportedAt.plusSeconds(600);
        Instant inquiryAt = claimedAt.plusSeconds(600);
        Instant statementAt = inquiryAt.plusSeconds(1_800);
        Instant decidedAt = statementAt.plusSeconds(600);
        long caseId = database.insert("""
                insert into moderation_case (case_type, created_at, claimed_manager_id, claimed_at, target_type,
                    target_id, reporter_account_id, reported_reason, case_status, decision_kind, reason_text,
                    decided_by, decided_at, updated_at)
                values ('report', ?, ?, ?, 'comment', ?, ?, ?, 'decided', 'violation', ?, ?, ?, ?)
                returning id
                """, reportedAt, managerId, claimedAt, commentId, reporterId,
                "评论包含贬损性内容，请管理员核查", "评论含贬损性内容，经核查后移除",
                managerId, decidedAt, decidedAt);
        long conversationId = database.insert("""
                insert into case_conversation (case_id, related_account_id, seq_head, created_at, archived_at)
                values (?, ?, 2, ?, null)
                returning case_conversation_id
                """, caseId, authorId, inquiryAt);
        long inquiryMessageId = caseMessage(database, conversationId, 1, "inquiry", "manager", managerId,
                "请说明这条评论是否针对商品本身，以及发布时的意图。", inquiryAt);
        long statementMessageId = caseMessage(database, conversationId, 2, "statement", "account", authorId,
                "我认可这条评论措辞不当，后续会围绕商品事实沟通。", statementAt);
        database.update("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, note, resolution)
                values (?, 'claim', ?, ?, 'manager', null, null)
                """, caseId, managerId, claimedAt);
        long inquiryActionId = database.insert("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, note, message_id, related_account_id)
                values (?, 'inquire', ?, ?, 'manager', '核实评论指向与措辞', ?, ?)
                returning id
                """, caseId, managerId, inquiryAt, inquiryMessageId, authorId);
        long statementActionId = database.insert("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, message_id, related_account_id, inquiry_action_id)
                values (?, 'statement', ?, ?, 'account', ?, ?, ?)
                returning id
                """, caseId, authorId, statementAt, statementMessageId, authorId, inquiryActionId);
        database.update("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, basis_ref)
                values (?, 'decide', ?, ?, 'manager', ?::jsonb)
                """, caseId, managerId, decidedAt, "[\"action:" + statementActionId + "\"]");

        String basisRef = "case:" + caseId;
        String enforcementId = "demo-remove-comment-" + commentId;
        database.update("""
                insert into case_enforcement (case_id, enforcement_id, action, target_type, target_id, basis_ref,
                    requested_by, requested_at, result_type, result_id, result_status, previous_state,
                    current_state, affected_scope, occurred_at)
                values (?, ?, 'remove_content', 'comment', ?, ?, ?, ?, 'product_comment', ?, 'applied',
                    'removed_at=null', 'removed_by_admin', ?::jsonb, ?)
                """, caseId, enforcementId, commentId, basisRef, managerId, decidedAt, commentId,
                "[{\"resource_type\":\"account\",\"resource_id\":\"" + authorId + "\"}]", decidedAt);
        database.update("""
                update product_comment
                   set removed_at = ?, removed_by_admin_id = ?, removed_reason = ?, basis_ref = ?
                 where comment_id = ?
                """, decidedAt, managerId, "评论含贬损性内容，经举报核查后移除",
                basisRef + ":enforcement:" + enforcementId, commentId);
        int appealWindow = context.config().integerOrDefault("project1.case.appeal-window-seconds", 604_800);
        database.update("""
                insert into case_appeal_eligibility (case_id, account_id, appeal_deadline_at, basis_ref, created_at)
                values (?, ?, ?, ?, ?)
                """, caseId, authorId, decidedAt.plusSeconds(appealWindow), basisRef, decidedAt);
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("report_" + comment.product() + "_comment",
                "report_case", caseId));
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("case_" + comment.product() + "_comment",
                "case", caseId));
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("conversation_" + comment.product() + "_comment",
                "case_conversation", conversationId));
    }

    private static void seedFavorites(SeedDatabase database, Instant now, Map<String, Long> users,
                                      Map<String, Long> productIds) throws SQLException {
        database.update("""
                insert into product_favorite (account_id, product_id, created_at)
                values (?, ?, ?)
                """, users.get("buyer"), productIds.get("mountain_bike"), now.minusSeconds(2L * 86_400));
        database.update("""
                insert into product_favorite (account_id, product_id, created_at)
                values (?, ?, ?)
                """, users.get("buyer3"), productIds.get("kindle"), now.minusSeconds(3L * 86_400));
    }

    private static void seedTrades(SeedContext context, SeedDatabase database, Instant now,
                                   Map<String, Long> users, Map<String, Long> productIds,
                                   Map<String, Long> productImageFiles, SeedOutcome outcome) throws SQLException {
        for (var trade : DemoCatalog.TRADES) {
            long productId = productIds.get(trade.product());
            long sellerId = users.get(DemoCatalog.PRODUCTS.stream()
                    .filter(product -> product.key().equals(trade.product())).findFirst().orElseThrow().seller());
            long buyerId = users.get(trade.buyer());
            Instant requestedAt = now.minusSeconds((long) (trade.daysAgo() * 86_400));
            Instant respondedAt = trade.acceptedDaysAgo() == null ? null
                    : now.minusSeconds((long) (trade.acceptedDaysAgo() * 86_400));
            Instant endedAt = trade.finishedDaysAgo() == null ? null
                    : now.minusSeconds((long) (trade.finishedDaysAgo() * 86_400));
            String terminalReason = "completed".equals(trade.status()) ? "completed" : null;
            Instant updatedAt = endedAt == null ? respondedAt == null ? requestedAt : respondedAt : endedAt;
            long tradeId = database.insert("""
                    insert into trade (product_id, buyer_id, seller_id, status, request_note, active_agreement_id,
                        version, close_reason, terminal_reason, requested_at, responded_at, ended_at,
                        created_at, updated_at)
                    values (?, ?, ?, ?, ?, null, 1, null, ?, ?, ?, ?, ?, ?)
                    returning id
                    """, productId, buyerId, sellerId, trade.status(), "演示交易 " + trade.key(), terminalReason,
                    requestedAt, respondedAt, endedAt, requestedAt, updatedAt);
            database.update("""
                    insert into trade_item_snapshot (trade_id, product_id, title, description, price_cents,
                        category_names, image_file_ids, captured_at)
                    select ?, ?, title, description, price_cents,
                           array(select n.name from product_category pc join category_name n
                                  on n.category_id = pc.category_id and n.deactivated_at is null and n.name_kind = 'main'
                                 where pc.product_id = ? and pc.removed_at is null),
                           array[?]::bigint[], ?
                      from product where product_id = ?
                    """, tradeId, productId, productId, productImageFiles.get(trade.product()), requestedAt, productId);
            database.update("""
                    insert into trade_purchase_product_snapshot
                        (trade_id, content_version, title, description, price_cents, captured_at)
                    select ?, content_version, title, description, price_cents, ?
                      from product where product_id = ?
                    """, tradeId, requestedAt, productId);
            database.update("""
                    update product set occupied_by_trade_id = ?, updated_at = ?
                     where product_id = ? and lifecycle_state = 'in_trade'
                    """, tradeId, respondedAt, productId);
            long conversationId = createTradeConversation(database, tradeId, trade, requestedAt, users, sellerId,
                    buyerId);
            Long agreementId = null;
            if (trade.agreement()) {
                long amountCents = DemoCatalog.PRODUCTS.stream()
                        .filter(product -> product.key().equals(trade.product())).findFirst().orElseThrow()
                        .priceCents();
                agreementId = createAgreement(database, tradeId, sellerId, trade, requestedAt, respondedAt,
                        amountCents);
                database.update("update trade set active_agreement_id = ? where id = ?", agreementId, tradeId);
                createConfirmations(context, database, tradeId, agreementId, trade, buyerId, sellerId, endedAt, now);
            }
            createTradeReview(database, trade, tradeId, buyerId, sellerId, endedAt);
            if (trade.frozen()) {
                createFrozenTradeCase(database, now, tradeId, sellerId, buyerId, trade, outcome);
            }
            createTradeHistory(database, trade, tradeId, buyerId, sellerId, agreementId, requestedAt,
                    respondedAt, endedAt);
            database.update("""
                    insert into trade_read_progress (trade_conversation_id, account_id, last_read_seq, last_read_at)
                    select ?, ?, seq_head, created_at from trade_conversation where trade_conversation_id = ?
                    on conflict do nothing
                    """, conversationId, buyerId, conversationId);
            database.update("""
                    insert into trade_read_progress (trade_conversation_id, account_id, last_read_seq, last_read_at)
                    select ?, ?, seq_head, created_at from trade_conversation where trade_conversation_id = ?
                    on conflict do nothing
                    """, conversationId, sellerId, conversationId);
            outcome.scenarios.add(new SeedOutcome.ScenarioRef("trade_" + trade.key(), "trade", tradeId));
            outcome.scenarios.add(new SeedOutcome.ScenarioRef("conversation_" + trade.key(), "trade_conversation",
                    conversationId));
        }
    }

    private static long createTradeConversation(SeedDatabase database, long tradeId, DemoCatalog.Trade trade,
                                                Instant requestedAt, Map<String, Long> users, long sellerId,
                                                long buyerId) throws SQLException {
        long conversationId = database.insert("""
                insert into trade_conversation (trade_id, seq_head, created_at, archived_at)
                values (?, ?, ?, ?)
                returning trade_conversation_id
                """, tradeId, DemoCatalog.TRADES.stream().filter(item -> item.key().equals(trade.key()))
                .findFirst().orElseThrow().messages().size(), requestedAt,
                "completed".equals(trade.status()) ? requestedAt.plusSeconds(20 * 86_400L) : null);
        int seq = 0;
        for (var message : trade.messages()) {
            seq++;
            Instant createdAt = requestedAt.plusSeconds(seq * 600L);
            if (message.sender() == null) {
                database.update("""
                        insert into trade_message (trade_conversation_id, seq, sender_kind, sender_account_id,
                            message_type, body, business_event_id, event_type, source_type, source_id, created_at)
                        values (?, ?, 'system', null, 'system_event', ?, ?, 'seed.trade_event', null, null, ?)
                        """, conversationId, seq, message.body(), UUID.randomUUID(), createdAt);
            } else {
                database.update("""
                        insert into trade_message (trade_conversation_id, seq, sender_kind, sender_account_id,
                            message_type, body, business_event_id, event_type, source_type, source_id, created_at)
                        values (?, ?, 'account', ?, 'text', ?, null, null, null, null, ?)
                        """, conversationId, seq, users.get(message.sender()), message.body(), createdAt);
            }
        }
        return conversationId;
    }

    private static long createAgreement(SeedDatabase database, long tradeId, long sellerId,
                                        DemoCatalog.Trade trade, Instant requestedAt, Instant respondedAt,
                                        long amountCents) throws SQLException {
        Instant proposedAt = respondedAt == null ? requestedAt.plusSeconds(600) : respondedAt.plusSeconds(600);
        return database.insert("""
                insert into agreement_version (trade_id, base_agreement_id, version_no, status, proposed_by,
                    delivery_at, delivery_place_text, delivery_method, amount_cents, payment_method, payment_timing,
                    proposed_at, business_event_id)
                values (?, null, 1, 'effective', ?, ?, '图书馆南门', '当面交付', ?, '当面支付', '交付时', ?, ?)
                returning id
                """, tradeId, sellerId, proposedAt.plusSeconds(86_400), amountCents, proposedAt, UUID.randomUUID());
    }

    private static void createConfirmations(SeedContext context, SeedDatabase database, long tradeId,
                                            long agreementId, DemoCatalog.Trade trade, long buyerId, long sellerId,
                                            Instant endedAt, Instant now) throws SQLException {
        if ("both".equals(trade.confirmation()) || "one".equals(trade.confirmation())) {
            database.update("""
                    insert into trade_confirmation (trade_id, agreement_id, confirmer_id, note, submitted_at,
                        invalidated_at, invalidation_reason, business_event_id)
                    values (?, ?, ?, '演示确认', ?, null, null, ?)
                    """, tradeId, agreementId, buyerId, endedAt == null ? now.minusSeconds(86_400) : endedAt,
                    UUID.randomUUID());
        }
        if ("both".equals(trade.confirmation())) {
            database.update("""
                    insert into trade_confirmation (trade_id, agreement_id, confirmer_id, note, submitted_at,
                        invalidated_at, invalidation_reason, business_event_id)
                    values (?, ?, ?, '演示确认', ?, null, null, ?)
                    """, tradeId, agreementId, sellerId, endedAt == null ? now.minusSeconds(86_000) : endedAt,
                    UUID.randomUUID());
        }
        if ("one".equals(trade.confirmation())) {
            int waitSeconds = context.config().integerOrDefault("TRADE_CONFIRMATION_WAIT_SECONDS", 604800);
            database.update("""
                    insert into confirmation_wait (trade_id, started_at, active_since, accumulated_seconds,
                        wait_seconds, policy_version, ended_at, end_reason)
                    values (?, ?, ?, 0, ?, 'seed-v1', null, null)
                    """, tradeId, now.minusSeconds(86_400), now.minusSeconds(86_400), waitSeconds);
        }
    }

    private static void createTradeReview(SeedDatabase database, DemoCatalog.Trade trade, long tradeId,
                                          long buyerId, long sellerId, Instant endedAt) throws SQLException {
        if (trade.rating() == null) {
            return;
        }
        database.update("""
                insert into trade_review (trade_id, reviewer_id, reviewee_id, rating, content, visible, created_at)
                values (?, ?, ?, ?, ?, true, ?)
                """, tradeId, buyerId, sellerId, trade.rating(), trade.review(),
                endedAt == null ? Instant.now() : endedAt.plusSeconds(3_600));
    }

    private static void createFrozenTradeCase(SeedDatabase database, Instant now, long tradeId, long sellerId,
                                              long buyerId, DemoCatalog.Trade trade, SeedOutcome outcome)
            throws SQLException {
        long caseId = database.insert("""
                insert into moderation_case (case_type, created_at, claimed_manager_id, claimed_at, target_type,
                    target_id, case_status, updated_at)
                values ('exception', ?, null, null, 'trade', ?, 'pending', ?)
                returning id
                """, now.minusSeconds(2L * 86_400), tradeId, now.minusSeconds(2L * 86_400));
        database.update("""
                insert into trade_freeze (trade_id, source, source_ref, reason, started_at, ended_at, ended_by)
                values (?, 'admin_case', ?, ?, ?, null, null)
                """, tradeId, caseId, trade.freezeReason(), now.minusSeconds(2L * 86_400));
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("case_trade_frozen_" + trade.key(), "case", caseId));
    }

    private static void createTradeHistory(SeedDatabase database, DemoCatalog.Trade trade, long tradeId,
                                           long buyerId, long sellerId, Long agreementId, Instant requestedAt,
                                           Instant respondedAt, Instant endedAt) throws SQLException {
        transition(database, tradeId, "request.create", null, "pending_acceptance", "buyer", buyerId,
                requestedAt, null, null);
        if (respondedAt != null) {
            transition(database, tradeId, "request.accept", "pending_acceptance", "in_progress", "seller",
                    sellerId, respondedAt, null, null);
        }
        if (agreementId != null) {
            transition(database, tradeId, "agreement.propose", "in_progress", "in_progress", "seller", sellerId,
                    respondedAt == null ? requestedAt : respondedAt.plusSeconds(600), agreementId, null);
            transition(database, tradeId, "agreement.accept", "in_progress", "in_progress", "buyer", buyerId,
                    respondedAt == null ? requestedAt : respondedAt.plusSeconds(700), agreementId, null);
        }
        if ("both".equals(trade.confirmation())) {
            transition(database, tradeId, "completion.confirm", "in_progress", "completed", "seller", sellerId,
                    endedAt == null ? requestedAt : endedAt, agreementId, null);
            transition(database, tradeId, "trade.completed", "completed", "completed", "system", null,
                    endedAt == null ? requestedAt : endedAt, agreementId, null);
        } else if ("one".equals(trade.confirmation())) {
            transition(database, tradeId, "completion.confirm", "in_progress", "in_progress", "buyer", buyerId,
                    endedAt == null ? requestedAt.plusSeconds(86_400) : endedAt, agreementId, null);
        }
    }

    private static void transition(SeedDatabase database, long tradeId, String action, String from, String to,
                                   String actorKind, Long actorId, Instant at, Long agreementId, Long caseId)
            throws SQLException {
        database.update("""
                insert into trade_state_history (trade_id, action, from_status, to_status, from_phase, to_phase,
                    actor_kind, actor_id, reason, basis_ref, case_id, agreement_id, agreement_decision_id,
                    confirmation_id, cancellation_id, cancellation_decision_id, dispute_id,
                    dispute_resolution_confirmation_id, business_event_id, created_at)
                values (?, ?, ?, ?, null, null, ?, ?, null, null, ?, ?, null, null, null, null, null, null, ?, ?)
                """, tradeId, action, from, to, actorKind, actorId, caseId, agreementId, UUID.randomUUID(), at);
    }

    private static void seedReportCase(SeedContext context, SeedDatabase database, Instant now,
                                       Map<String, Long> users, Map<String, Long> productIds,
                                       SeedOutcome outcome) throws SQLException {
        long productId = productIds.get("powerbank");
        long reporterId = users.get("outsider");
        long sellerId = users.get("seller2");
        long managerId = outcome.managerId;
        Instant createdAt = now.minusSeconds(8L * 86_400);
        Instant decidedAt = now.minusSeconds(6L * 86_400);
        long caseId = database.insert("""
                insert into moderation_case (case_type, created_at, claimed_manager_id, claimed_at, target_type,
                    target_id, reporter_account_id, reported_reason, case_status, decision_kind, reason_text,
                    decided_by, decided_at, public_summary, public_reason, public_result_at, published_by,
                    updated_at)
                values ('report', ?, ?, ?, 'product', ?, ?, ?, 'decided', 'violation', ?, ?, ?, ?, ?, ?, ?, ?)
                returning id
                """, createdAt, managerId, createdAt.plusSeconds(3_600), productId, reporterId,
                "充电宝外壳鼓包仍在出售，存在安全隐患", "商品存在电池鼓包安全隐患", managerId, decidedAt,
                "经核查，商品存在电池鼓包安全隐患，已停止公开访问并提醒卖方妥善处理",
                "商品图与描述均显示外壳鼓包，继续公开交易存在安全风险", decidedAt, managerId, decidedAt);
        database.update("""
                insert into product_case_snapshot (case_id, product_id, content_version, title, description,
                    price_cents, captured_at)
                select ?, product_id, content_version, title, description, price_cents, ?
                  from product where product_id = ?
                """, caseId, createdAt, productId);
        long conversationId = database.insert("""
                insert into case_conversation (case_id, related_account_id, seq_head, created_at, archived_at)
                values (?, ?, 1, ?, null)
                returning case_conversation_id
                """, caseId, reporterId, createdAt);
        caseMessage(database, conversationId, 1, "statement", "account", reporterId,
                "商品描述写了轻微鼓包但仍作为正常商品出售，请管理员核查。", createdAt.plusSeconds(60));
        Instant inquiryAt = createdAt.plusSeconds(3_700);
        Instant statementAt = inquiryAt.plusSeconds(3_600);
        long sellerConversationId = database.insert("""
                insert into case_conversation (case_id, related_account_id, seq_head, created_at, archived_at)
                values (?, ?, 3, ?, null)
                returning case_conversation_id
                """, caseId, sellerId, inquiryAt);
        long inquiryMessageId = caseMessage(database, sellerConversationId, 1, "inquiry", "manager", managerId,
                "请说明外壳鼓包情况，以及是否仍能安全使用。", inquiryAt);
        long statementMessageId = caseMessage(database, sellerConversationId, 2, "statement", "account", sellerId,
                "右侧外壳有一点鼓包。我已停止使用，可以配合回收。", statementAt);
        database.update("""
                insert into case_message (case_conversation_id, seq, message_kind, sender_kind,
                    body, business_event_id, event_type, created_at)
                values (?, 3, 'system_notice', 'system', ?, ?, 'case.system_notice', ?)
                """, sellerConversationId, "商品已停止公开访问。你可以在申辩期内提交说明。",
                UUID.randomUUID(), decidedAt);
        database.update("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, note, resolution)
                values (?, 'claim', ?, ?, 'manager', null, null)
                """, caseId, managerId, createdAt.plusSeconds(3_600));
        long inquiryActionId = database.insert("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, note, message_id, related_account_id)
                values (?, 'inquire', ?, ?, 'manager', '核实电池鼓包情况', ?, ?)
                returning id
                """, caseId, managerId, inquiryAt, inquiryMessageId, sellerId);
        long statementActionId = database.insert("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, message_id, related_account_id, inquiry_action_id)
                values (?, 'statement', ?, ?, 'account', ?, ?, ?)
                returning id
                """, caseId, sellerId, statementAt, statementMessageId, sellerId, inquiryActionId);
        database.update("""
                insert into moderation_case_action (case_id, action_kind, actor_account_id, occurred_at,
                    actor_kind, basis_ref)
                values (?, 'decide', ?, ?, 'manager', ?::jsonb)
                """, caseId, managerId, decidedAt, "[\"action:" + statementActionId + "\"]");
        long evidenceIndex = 0;
        for (var upload : outcome.uploadedFiles) {
            if (upload.asset().purpose() != io.github.iy88.project1.storage.FilePurpose.CASE_EVIDENCE) {
                continue;
            }
            long fileId = SeedFileRegistry.record(database, upload, reporterId, context.bucket(),
                    "seed-" + context.configVersion(), now);
            long referenceId = SeedFileRegistry.attach(database, fileId, "case", caseId, "evidence",
                    Long.toString(reporterId), createdAt.plusSeconds(120 + evidenceIndex));
            database.update("""
                    insert into case_evidence (case_id, evidence_kind, file_id, file_reference_id,
                        source_ref_type, source_ref_id, required_scope, submitted_by, submitted_at)
                    values (?, 'submitter_attachment', ?, ?, null, null, null, ?, ?)
                    """, caseId, fileId, referenceId, reporterId, createdAt.plusSeconds(120 + evidenceIndex));
            evidenceIndex++;
        }
        String basisRef = "case:" + caseId;
        long restrictionId = database.insert("""
                insert into product_display_restriction (product_id, source_type, source_ref_id, reason,
                    basis_ref, created_by, created_at)
                values (?, 'admin_case', ?, ?, ?, ?, ?)
                returning restriction_id
                """, productId, caseId, "存在电池鼓包安全隐患，已停止公开访问", basisRef, managerId, decidedAt);
        database.update("""
                insert into case_enforcement (case_id, enforcement_id, action, target_type, target_id, basis_ref,
                    requested_by, requested_at, result_type, result_id, result_status, previous_state,
                    current_state, affected_scope, occurred_at)
                values (?, 'demo-hide-product', 'withdraw_public_access', 'product', ?, ?, ?, ?,
                    'product_display_restriction', ?, 'applied', 'display=visible', 'display=restricted',
                    ?::jsonb, ?)
                """, caseId, productId, basisRef, managerId, decidedAt, restrictionId,
                "[{\"resource_type\":\"account\",\"resource_id\":\"" + sellerId + "\"}]", decidedAt);
        int appealWindow = context.config().integerOrDefault("project1.case.appeal-window-seconds", 604_800);
        database.update("""
                insert into case_appeal_eligibility (case_id, account_id, appeal_deadline_at, basis_ref, created_at)
                values (?, ?, ?, ?, ?)
                """, caseId, sellerId, decidedAt.plusSeconds(appealWindow), basisRef, decidedAt);
        database.update("""
                insert into notification (recipient_account_id, intent_key, event_type, source_type, source_id,
                    template_key, template_version, display_params, occurred_at, created_at, read_at)
                values (?, ?, 'case.result_published', 'case', ?, 'case.result', '1',
                    ?::jsonb, ?, ?, null)
                """, reporterId, "case:" + caseId + ":result_published", caseId,
                "{\"case_id\":\"" + caseId + "\"}", decidedAt, decidedAt);
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("powerbank_seller_appeal", "case_conversation",
                sellerConversationId));
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("report_powerbank", "report_case", caseId));
        outcome.scenarios.add(new SeedOutcome.ScenarioRef("case_report_powerbank", "case", caseId));
    }

    private static long caseMessage(SeedDatabase database, long conversationId, int seq, String kind,
                                    String senderKind, long senderId, String body, Instant at) throws SQLException {
        return database.insert("""
                insert into case_message (case_conversation_id, seq, message_kind, sender_kind,
                    sender_account_id, body, business_event_id, event_type, created_at)
                values (?, ?, ?, ?, ?, ?, null, null, ?)
                returning case_message_id
                """, conversationId, seq, kind, senderKind, senderId, body, at);
    }

    private static void seedChats(SeedContext context, SeedDatabase database, Instant now,
                                  Map<String, Long> users, SeedOutcome outcome) throws SQLException {
        for (var chat : DemoCatalog.CHATS) {
            long left = users.get(chat.left());
            long right = users.get(chat.right());
            long low = Math.min(left, right);
            long high = Math.max(left, right);
            Instant createdAt = now.minusSeconds((long) (chat.daysAgo() * 86_400));
            long conversationId = database.insert("""
                    insert into chat_conversation (account_low_id, account_high_id, seq_head, created_at)
                    values (?, ?, ?, ?)
                    returning chat_conversation_id
                    """, low, high, chat.messages().size(), createdAt);
            int seq = 0;
            for (var message : chat.messages()) {
                seq++;
                database.update("""
                        insert into chat_message (chat_conversation_id, seq, sender_account_id, body, created_at)
                        values (?, ?, ?, ?, ?)
                        """, conversationId, seq, users.get(message.sender()), message.body(),
                        createdAt.plusSeconds(seq * 300L));
            }
            database.update("""
                    insert into chat_read_progress (chat_conversation_id, account_id, last_read_seq, last_read_at)
                    values (?, ?, ?, ?)
                    """, conversationId, left, chat.messages().size(), createdAt.plusSeconds(1_000));
            database.update("""
                    insert into chat_read_progress (chat_conversation_id, account_id, last_read_seq, last_read_at)
                    values (?, ?, ?, ?)
                    """, conversationId, right, Math.max(1, chat.messages().size() - 1),
                    createdAt.plusSeconds(900));
            outcome.conversationIds.add(conversationId);
            outcome.scenarios.add(new SeedOutcome.ScenarioRef(chat.key(), "chat", conversationId));
        }
    }
}
