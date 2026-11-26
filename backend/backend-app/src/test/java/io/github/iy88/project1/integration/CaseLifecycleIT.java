package io.github.iy88.project1.integration;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.AccountCookies;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CaseApplication;
import io.github.iy88.project1.casemanagement.application.CaseCommands;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseQueries;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.CaseCommentAccess;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Real PostgreSQL/Spring integration of the case lifecycle: claim competition, inquiry thread,
 * decision with a subject execution, appeal blocking the close, archival and anonymous publication.
 *
 * <p>The subject execution port is replaced with a deterministic fake because account/product
 * execution belongs to S4-01 (#81); every other dependency (accounts, case tables, conversation,
 * notifications, files, transactions) is the production implementation against an isolated
 * database. The database is migrated by the handover script and dropped after the run.</p>
 */
class CaseLifecycleIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final String PASSWORD = "CaseIntegrationFixture1!";
    private static final String ORIGIN = "http://127.0.0.1:3000";
    private static final AtomicReference<Long> RELATED = new AtomicReference<>();
    private static final AtomicReference<Long> REPORTER = new AtomicReference<>();
    private static final AtomicReference<Long> MANAGER_1 = new AtomicReference<>();
    private static final AtomicReference<Long> MANAGER_2 = new AtomicReference<>();
    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static CaseApplication cases;
    private static CaseQueries queries;
    private static CaseLifecycleStore store;

    @BeforeAll
    static void startApplication() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        String namespace = properties.getProperty("REDIS_NAMESPACE");
        properties.setProperty("REDIS_NAMESPACE", namespace + ":case:" + RUN_ID);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("CONFIG_VERSION", "case-it");
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        properties.setProperty("ACCOUNT_ENTRY_SIGNING_KEY", "case-it-entry-signing-key-0123456789abcdef");
        properties.setProperty("ACCOUNT_ENTRY_KEY_VERSION", "it-v1");
        properties.setProperty("project1.case.appealWindowSeconds", "86400");
        var application = new SpringApplication(BackendAppApplication.class, Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("case-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        cases = app.getBean(CaseApplication.class);
        queries = app.getBean(CaseQueries.class);
        store = app.getBean(CaseLifecycleStore.class);
        REPORTER.set(account("reporter-" + RUN_ID, "举报人", "user"));
        RELATED.set(account("related-" + RUN_ID, "相关用户", "user"));
        MANAGER_1.set(account("manager1-" + RUN_ID, "管理员一", "manager"));
        MANAGER_2.set(account("manager2-" + RUN_ID, "管理员二", "manager"));
    }

    @AfterAll
    static void stopApplication() {
        if (app != null) {
            try (var context = app) {
                // The isolated database is dropped by the handover script after this process exits.
            }
        }
    }

    @Test
    void claimCompetitionInquiryDecisionAppealCloseAndPublication() throws Exception {
        long reporter = REPORTER.get();
        long related = RELATED.get();
        var report = cases.submit(context(reporter), "submit-1", new CaseCommands.Report(
                new CaseCommands.Target("account", related, null, null), "虚假信息", "请核实", List.of()));
        long caseId = Long.parseLong(report.data().get("case_id").asString());
        assertThat(report.status()).isEqualTo(201);

        // Two managers claim at the same time: exactly one wins, the loser sees CASE_ALREADY_CLAIMED.
        var start = new CountDownLatch(1);
        var winners = new AtomicInteger();
        var conflicts = new AtomicInteger();
        try (var executor = Executors.newFixedThreadPool(2)) {
            for (long manager : List.of(MANAGER_1.get(), MANAGER_2.get())) {
                executor.submit(() -> {
                    try {
                        start.await();
                        cases.claim(context(manager), "claim-" + manager + "-" + RUN_ID, caseId);
                        winners.incrementAndGet();
                    } catch (BusinessError failure) {
                        if ("CASE_ALREADY_CLAIMED".equals(failure.code())) {
                            conflicts.incrementAndGet();
                        } else {
                            throw failure;
                        }
                    }
                    return null;
                });
            }
            start.countDown();
            executor.shutdown();
            assertThat(executor.awaitTermination(30, TimeUnit.SECONDS)).isTrue();
        }
        assertThat(winners.get()).isEqualTo(1);
        assertThat(conflicts.get()).isEqualTo(1);
        long manager = db.sql("select claimed_manager_id from moderation_case where id = ?")
                .param(caseId).query(Long.class).single();

        // Inquiry writes a manager message in the related account's thread and notifies that account.
        var inquiry = cases.inquire(context(manager), "inquiry-1", caseId,
                new CaseCommands.Inquiry(related, "请说明商品问题"));
        assertThat(inquiry.status()).isEqualTo(201);
        long inquiryActionId = Long.parseLong(inquiry.data().get("inquiry_action_id").asString());
        long threadId = storeThread(caseId, related);
        assertThat(db.sql("select count(*) from case_message where case_conversation_id = ?")
                .param(threadId).query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("select count(*) from notification where recipient_account_id = ?"
                + " and event_type = 'case.inquiry_created'").param(related).query(Long.class).single())
                .isEqualTo(1);

        // The related account answers the inquiry in the same thread.
        var statement = cases.postMessage(context(related), "statement-1", caseId,
                new CaseCommands.Message(threadId, CaseVocabulary.KIND_STATEMENT, "商品描述属实", inquiryActionId,
                        null, null, null));
        assertThat(statement.status()).isEqualTo(201);

        // Decision executes the subject fake, records the enforcement link and appeal eligibility.
        var decision = cases.decide(context(manager), "decision-1", caseId, new CaseCommands.Decision(
                CaseVocabulary.VIOLATION, "认定违规", List.of("case:" + caseId),
                List.of(new CaseCommands.Enforcement("restrict_account", "account", related, null))));
        assertThat(decision.status()).isEqualTo(201);
        assertThat(db.sql("select count(*) from case_enforcement where case_id = ?").param(caseId)
                .query(Long.class).single()).isEqualTo(1);
        assertThat(db.sql("select count(*) from case_appeal_eligibility where case_id = ? and account_id = ?")
                .param(caseId).param(related).query(Long.class).single()).isEqualTo(1);

        // The appeal window is open: closing is rejected before the window elapses.
        assertThatThrownBy(() -> cases.close(context(manager), "close-1", caseId))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_APPEAL_WINDOW_OPEN"));

        var appeal = cases.postMessage(context(related), "appeal-1", caseId,
                new CaseCommands.Message(threadId, CaseVocabulary.KIND_APPEAL, "请求复核", null, null, null, null));
        assertThat(appeal.status()).isEqualTo(201);
        long appealActionId = store.appealOf(caseId, related).orElseThrow().actionId();
        assertThat(queries.detail(context(manager), caseId).path("pending_appeals"))
                .singleElement().satisfies(item -> {
                    assertThat(item.path("appeal_action_id").asString()).isEqualTo(Long.toString(appealActionId));
                    assertThat(item.path("related_account_id").asString()).isEqualTo(Long.toString(related));
                    assertThat(item.path("thread").path("conversation_id").asString()).isEqualTo(Long.toString(threadId));
                });
        assertThat(queries.detail(context(reporter), caseId).has("pending_appeals")).isFalse();
        assertThat(queries.detail(context(related), caseId).has("pending_appeals")).isFalse();

        var resolution = cases.postMessage(context(manager), "resolve-1", caseId,
                new CaseCommands.Message(threadId, CaseVocabulary.KIND_MANAGER_REPLY, "维持原决定", null,
                        appealActionId, CaseVocabulary.RESOLUTION_UPHOLD, "依据"));
        assertThat(resolution.status()).isEqualTo(201);
        assertThat(queries.detail(context(manager), caseId).path("pending_appeals")).isEmpty();

        // A resolved appeal no longer blocks, but the deadline still does.
        assertThatThrownBy(() -> cases.close(context(manager), "close-2", caseId))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_APPEAL_WINDOW_OPEN"));
        db.sql("update case_appeal_eligibility set appeal_deadline_at = statement_timestamp() - interval '1 minute'"
                + " where case_id = ?").param(caseId).update();

        var closed = cases.close(context(manager), "close-3", caseId);
        assertThat(closed.status()).isEqualTo(200);
        assertThat(db.sql("select archived_at from moderation_case where id = ?").param(caseId)
                .query(OffsetDateTime.class).single()).isNotNull();
        assertThat(db.sql("select archived_at from case_conversation where case_id = ?").param(caseId)
                .query(OffsetDateTime.class).optional()).isPresent();
        assertThat(store.actions(caseId).stream()
                .anyMatch(action -> CaseVocabulary.ACTION_CLOSE.equals(action.actionKind()))).isTrue();

        // Publication exposes only the anonymous summary and reason, never account identities.
        var published = cases.publish(context(manager), "publish-1", caseId,
                new CaseCommands.Publish("认定违规", "依据证据"));
        assertThat(published.status()).isEqualTo(200);
        var results = queries.results(context(related), "account", related, null, null, 1, 20);
        assertThat(results.get("total").asLong()).isEqualTo(1);
        JsonNode item = results.get("items").get(0);
        assertThat(item.get("public_summary").asString()).isEqualTo("认定违规");
        assertThat(item.get("public_reason").asString()).isEqualTo("依据证据");
        assertThat(item.has("account_id")).isFalse();

        // The detail projection follows the caller's viewpoint.
        var managerDetail = queries.detail(context(manager), caseId);
        assertThat(managerDetail.get("viewpoint").asString()).isEqualTo("manager");
        assertThat(managerDetail.get("archived_at").isNull()).isFalse();
        var reporterDetail = queries.detail(context(reporter), caseId);
        assertThat(reporterDetail.get("viewpoint").asString()).isEqualTo("reporter");
        assertThat(reporterDetail.get("reason_text").asString()).isEqualTo("依据证据");
    }

    @Test
    void liftRevertsTheDecisionEnforcementAndIsIdempotent() {
        long reporter = REPORTER.get();
        long related2 = account("related2-" + RUN_ID, "相关用户二", "user");
        var submitted = cases.submit(context(reporter), "submit-lift-" + RUN_ID, new CaseCommands.Report(
                new CaseCommands.Target("account", related2, null, null), "虚假信息", null, List.of()));
        long caseId = Long.parseLong(submitted.data().get("case_id").asString());
        cases.claim(context(MANAGER_1.get()), "claim-lift-" + RUN_ID, caseId);
        var decision = cases.decide(context(MANAGER_1.get()), "decision-lift-" + RUN_ID, caseId,
                new CaseCommands.Decision(CaseVocabulary.VIOLATION, "认定违规", List.of("case:" + caseId),
                        List.of(new CaseCommands.Enforcement("restrict_account", "account", related2, null))));
        String enforcementId = decision.data().get("enforcements").get(0).get("enforcement_id").asString();

        var lifted = cases.lift(context(MANAGER_1.get()), "lift-" + RUN_ID, caseId, enforcementId, "解除限制");
        assertThat(lifted.status()).isEqualTo(200);
        assertThat(lifted.data().get("restored_scope").get(0).asString()).isEqualTo("account:" + related2);
        assertThat(db.sql("select lifted_at from case_enforcement where case_id = ? and enforcement_id = ?")
                .param(caseId).param(enforcementId).query(OffsetDateTime.class).single()).isNotNull();
        assertThat(store.actions(caseId).stream()
                .anyMatch(action -> CaseVocabulary.ACTION_LIFT.equals(action.actionKind()))).isTrue();

        var repeated = cases.lift(context(MANAGER_1.get()), "lift-again-" + RUN_ID, caseId, enforcementId,
                "再次解除");
        assertThat(repeated.status()).isEqualTo(200);
        assertThat(repeated.data().get("lifted_at").asString())
                .isEqualTo(lifted.data().get("lifted_at").asString());
    }

    @Test
    void failedExecutionKeepsAFailureTrailWithoutSubjectChanges() {
        long related3 = account("related3-" + RUN_ID, "相关用户三", "user");
        var submitted = cases.submit(context(REPORTER.get()), "submit-fail-" + RUN_ID, new CaseCommands.Report(
                new CaseCommands.Target("account", related3, null, null), "虚假信息", null, List.of()));
        long caseId = Long.parseLong(submitted.data().get("case_id").asString());

        store.recordFailure(caseId, "enf-fail", "restrict_account", "account", related3, "case:" + caseId,
                MANAGER_1.get(), "TARGET_STATE_CONFLICT", "目标状态冲突", Instant.now());

        var row = db.sql("""
                        select result_status, failure_code, failure_reason from case_enforcement
                         where case_id = ? and enforcement_id = ?
                        """)
                .param(caseId).param("enf-fail")
                .query((rs, index) -> List.of(rs.getString("result_status"), rs.getString("failure_code"),
                        rs.getString("failure_reason")))
                .single();
        assertThat(row).containsExactly("failed", "TARGET_STATE_CONFLICT", "目标状态冲突");
    }

    @Test
    void closedReportRejectsANewSubmissionForTheSameObject() {
        long reporter = REPORTER.get();
        long related = account("closed-report-" + RUN_ID, "已结案目标", "user");
        var target = new CaseCommands.Target("account", related, null, null);
        long closedCase = db.sql("""
                        insert into moderation_case (case_type, created_at, updated_at, target_type, target_id,
                            reporter_account_id, reported_reason, case_status, decision_kind, reason_text,
                            decided_by, decided_at, archived_at)
                        values ('report', statement_timestamp(), statement_timestamp(), 'account', ?, ?, '旧举报',
                            'decided', 'no_action', '不予处理', ?, statement_timestamp(), statement_timestamp())
                        returning id
                        """)
                .param(related).param(reporter).param(MANAGER_1.get()).query(Long.class).single();
        assertThatThrownBy(() -> cases.submit(context(reporter), "resubmit-" + RUN_ID,
                new CaseCommands.Report(target, "再次举报", null, List.of())))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("CASE_CLOSED"));
        // The archived row is still readable through the reporter viewpoint.
        assertThat(queries.detail(context(reporter), closedCase).get("case_id").asString())
                .isEqualTo(Long.toString(closedCase));
    }

    @Test
    void reportsVisibleCommentsAndReceivedEvaluationsAndKeepsTheirAuthorsForInquiry() {
        long reporter = REPORTER.get();
        long author = account("report-author-" + RUN_ID, "举报事项作者", "user");
        long outsider = account("report-outsider-" + RUN_ID, "旁观者", "user");
        long product = db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, '举报测试商品', 'Fixture', 100, 'public') returning product_id
                """).param(author).query(Long.class).single();
        long comment = db.sql("""
                insert into product_comment (product_id, author_account_id, body)
                values (?, ?, '举报测试评论') returning comment_id
                """).param(product).param(author).query(Long.class).single();

        var commentTarget = new CaseCommands.Target("comment", comment, null, null);
        assertInvalidReport(author, "own-comment", commentTarget);
        var commentReport = cases.submit(context(reporter), "report-comment", reportFor(commentTarget));
        assertThat(commentReport.status()).isEqualTo(201);
        long commentCase = Long.parseLong(commentReport.data().path("case_id").asString());
        db.sql("update product_comment set deleted_at = statement_timestamp() where comment_id = ?")
                .param(comment).update();
        assertInvalidReport(outsider, "removed-comment", commentTarget);
        inquireAuthor(commentCase, author, "comment");

        long trade = db.sql("""
                insert into trade (product_id, buyer_id, seller_id, status, terminal_reason,
                                   requested_at, ended_at, created_at, updated_at)
                values (?, ?, ?, 'completed', 'completed', now(), now(), now(), now()) returning id
                """).param(product).param(reporter).param(author).query(Long.class).single();
        long review = db.sql("""
                insert into trade_review (trade_id, reviewer_id, reviewee_id, rating, content, created_at)
                values (?, ?, ?, 3, '举报测试评价', now()) returning id
                """).param(trade).param(author).param(reporter).query(Long.class).single();

        var evaluationTarget = new CaseCommands.Target("evaluation", review, null, null);
        assertInvalidReport(outsider, "other-evaluation", evaluationTarget);
        assertInvalidReport(author, "own-evaluation", evaluationTarget);
        var evaluationReport = cases.submit(context(reporter), "report-evaluation", reportFor(evaluationTarget));
        assertThat(evaluationReport.status()).isEqualTo(201);
        long evaluationCase = Long.parseLong(evaluationReport.data().path("case_id").asString());
        db.sql("update trade_review set visible = false where id = ?").param(review).update();
        assertInvalidReport(reporter, "removed-evaluation", evaluationTarget);
        inquireAuthor(evaluationCase, author, "evaluation");

        var productTarget = new CaseCommands.Target("product", product, null, null);
        var productReport = cases.submit(context(reporter), "report-product-scope", reportFor(productTarget));
        long productCase = Long.parseLong(productReport.data().path("case_id").asString());
        long managerId = MANAGER_1.get();
        var caseAccess = app.getBean(CaseCommentAccess.class);
        assertThat(caseAccess.claimedForProduct(managerId, productCase, product)).isFalse();
        cases.claim(context(managerId), "claim-product-scope", productCase);
        assertThat(caseAccess.claimedForProduct(managerId, productCase, product)).isTrue();
        assertThat(caseAccess.claimedForProduct(MANAGER_2.get(), productCase, product)).isFalse();
        assertThat(caseAccess.claimedForProduct(managerId, commentCase, product)).isFalse();

        db.sql("delete from trade_review where id = ?").param(review).update();
        db.sql("delete from trade where id = ?").param(trade).update();
        db.sql("delete from product_comment where comment_id = ?").param(comment).update();
        db.sql("delete from product where product_id = ?").param(product).update();
    }

    private static CaseCommands.Report reportFor(CaseCommands.Target target) {
        return new CaseCommands.Report(target, "请核实内容", null, List.of());
    }

    private static void assertInvalidReport(long reporter, String key, CaseCommands.Target target) {
        assertThatThrownBy(() -> cases.submit(context(reporter), key, reportFor(target)))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("TARGET_INVALID"));
    }

    private static void inquireAuthor(long caseId, long author, String kind) {
        var manager = context(MANAGER_1.get());
        cases.claim(manager, "claim-" + kind, caseId);
        var inquiry = cases.inquire(manager, "inquire-" + kind, caseId, new CaseCommands.Inquiry(author, "请说明内容来源"));
        assertThat(inquiry.status()).isEqualTo(201);
        assertThat(store.find(caseId).orElseThrow().targetType()).isEqualTo(kind);
    }

    @Test
    void managementWorkbenchSeparatesPendingAndCompletedCasesAndProtectsOtherManagersDetails() throws Exception {
        long firstManager = MANAGER_1.get();
        long secondManager = MANAGER_2.get();
        var first = app.getBean(AccountService.class).login("manager1-" + RUN_ID + "@example.invalid", PASSWORD);
        var second = app.getBean(AccountService.class).login("manager2-" + RUN_ID + "@example.invalid", PASSWORD);
        long pending = workbenchReport("pending", null, false);
        long decided = workbenchReport("decided", firstManager, false);
        long firstClosed = workbenchReport("first-closed", firstManager, true);
        long secondClosed = workbenchReport("second-closed", secondManager, true);
        try (var http = HttpClient.newHttpClient()) {
            var shared = read(http, first, "/management/todos?ownership=unclaimed&kind=report", 200);
            assertThat(shared.path("items")).anySatisfy(item -> {
                assertThat(item.path("case_id").asString()).isEqualTo(Long.toString(pending));
                assertThat(item.path("manager_id").isNull()).isTrue();
                assertThat(item.path("completed_at").isNull()).isTrue();
            });
            var own = read(http, first, "/management/todos?ownership=mine&kind=all", 200);
            assertThat(own.path("items")).anySatisfy(item -> {
                assertThat(item.path("case_id").asString()).isEqualTo(Long.toString(decided));
                assertThat(item.path("decision_kind").asString()).isEqualTo("no_action");
                assertThat(item.path("completed_at").isNull()).isTrue();
            });
            String completed = "/management/todos?ownership=completed_all&kind=report&keyword="
                    + URLEncoder.encode("账户举报", StandardCharsets.UTF_8);
            var full = read(http, first, completed, 200);
            var ids = new ArrayList<String>();
            full.path("items").forEach(item -> ids.add(item.path("case_id").asString()));
            assertThat(ids).containsSubsequence(Long.toString(secondClosed), Long.toString(firstClosed))
                    .doesNotContain(Long.toString(decided), Long.toString(pending));
            var next = read(http, first, completed + "&page=2&page_size=1", 200);
            assertThat(next.path("total").asLong()).isEqualTo(full.path("total").asLong());
            assertThat(next.path("items")).singleElement().satisfies(item ->
                    assertThat(item.path("case_id").asString()).isEqualTo(ids.get(1)));
            assertThat(next.path("counts_by_kind").path("report").asLong())
                    .isEqualTo(next.path("total").asLong());
            String mine = "/management/todos?ownership=completed_mine&kind=all&keyword=";
            var mineFirst = read(http, first, mine + firstClosed, 200);
            assertThat(mineFirst.path("items")).singleElement().satisfies(item -> {
                assertThat(item.path("case_type").asString()).isEqualTo("report");
                assertThat(item.path("manager_id").asString()).isEqualTo(Long.toString(firstManager));
                assertThat(item.path("completed_at").isString()).isTrue();
                assertThat(item.path("summary").propertyNames()).containsExactly("title");
            });
            assertThat(read(http, second, mine + firstClosed, 200).path("total").asLong()).isZero();
            assertThat(read(http, first, mine + secondClosed, 200).path("total").asLong()).isZero();
            assertThat(read(http, first, "/management/todos?ownership=completed_all&kind=all"
                    + "&keyword=workbench-private-" + RUN_ID, 200).path("total").asLong()).isZero();
            read(http, second, "/cases/" + firstClosed, 404);
            read(http, first, "/cases/" + firstClosed, 200);
            read(http, first, "/management/todos?ownership=invalid", 422);
        } finally {
            var sessions = app.getBean(SessionService.class);
            for (var issued : List.of(first, second)) {
                sessions.revoke(sessions.authenticate(issued.token()));
            }
        }
    }

    private static long workbenchReport(String label, Long manager, boolean close) {
        long target = account("workbench-" + label + "-" + RUN_ID, label, "user");
        var report = cases.submit(context(REPORTER.get()), "workbench-report-" + label, new CaseCommands.Report(
                new CaseCommands.Target("account", target, null, null), "workbench-private-" + RUN_ID, null, List.of()));
        long caseId = Long.parseLong(report.data().path("case_id").asString());
        if (manager != null) {
            var managerContext = context(manager);
            cases.claim(managerContext, "workbench-claim-" + label, caseId);
            cases.decide(managerContext, "workbench-decide-" + label, caseId, new CaseCommands.Decision(
                    CaseVocabulary.NO_ACTION, "workbench-private-" + RUN_ID, List.of("case:" + caseId), List.of()));
            if (close) {
                cases.close(managerContext, "workbench-close-" + label, caseId);
            }
        }
        return caseId;
    }

    private static JsonNode read(HttpClient http, SessionService.Issued session, String path, int code) throws Exception {
        int port = ((ServletWebServerApplicationContext) app).getWebServer().getPort();
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/v1" + path))
                .header("Cookie", AccountCookies.SESSION + "=" + session.token()).GET().build();
        var response = http.send(request, HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as("GET %s: %s", path, response.body()).isEqualTo(code);
        return app.getBean(JsonMapper.class).readTree(response.body());
    }

    private static long storeThread(long caseId, long related) {
        return db.sql("select case_conversation_id from case_conversation where case_id = ? and related_account_id = ?")
                .param(caseId).param(related).query(Long.class).single();
    }

    private static long account(String name, String displayName, String role) {
        String email = name + "@example.invalid";
        return db.sql("""
                        insert into account (email, display_name, password_hash, credential_version, role)
                        values (?, ?, ?, 1, ?)
                        returning account_id
                        """)
                .param(email).param(displayName).param(app.getBean(PasswordHasher.class).hash(PASSWORD))
                .param(role).query(Long.class).single();
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(accountId), UUID.randomUUID(), null, 1L, "case-it");
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class Fixtures {
        @Bean
        @Primary
        CasePorts.Enforcement fakeCaseEnforcement() {
            return new CasePorts.Enforcement() {
                @Override
                public LockPlan plan(ExecutionContext context, long caseId,
                                     List<CaseRecords.EnforcementInstruction> instructions) {
                    return new LockPlan(Map.of(), Set.of());
                }

                @Override
                public List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction,
                                                                    ExecutionContext context, long caseId,
                                                                    String reason, String basisRef,
                                                                    List<CaseRecords.EnforcementInstruction> items,
                                                                    Instant occurredAt) {
                    var outcomes = new ArrayList<CaseRecords.EnforcementOutcome>();
                    for (var item : items) {
                        outcomes.add(new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(),
                                item.targetType(), item.targetId(), "account_restriction", item.targetId(),
                                "applied", "active", "restricted", List.of(item.targetId()), occurredAt));
                    }
                    return outcomes;
                }

                @Override
                public List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction,
                                                                    ExecutionContext context, long caseId,
                                                                    CaseRecords.Enforcement recorded,
                                                                    String resolution, String basisRef,
                                                                    String reason, Instant occurredAt) {
                    return List.of(new CaseRecords.EnforcementOutcome(recorded.enforcementId() + "-lift",
                            "lift_account_restriction", recorded.targetType(), recorded.targetId(),
                            "account_restriction", recorded.targetId(), "applied", "restricted", "active",
                            List.of(recorded.targetId()), occurredAt));
                }
            };
        }
    }
}
