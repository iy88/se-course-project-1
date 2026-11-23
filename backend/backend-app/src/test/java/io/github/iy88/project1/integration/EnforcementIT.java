package io.github.iy88.project1.integration;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.casemanagement.application.AccountEnforcementPort;
import io.github.iy88.project1.casemanagement.application.CaseAccess;
import io.github.iy88.project1.casemanagement.application.CaseEnforcementPort;
import io.github.iy88.project1.casemanagement.application.CaseEvidence;
import io.github.iy88.project1.casemanagement.application.ConversationEnforcementPort;
import io.github.iy88.project1.casemanagement.application.EnforcementAction;
import io.github.iy88.project1.casemanagement.application.EnforcementApplication;
import io.github.iy88.project1.casemanagement.application.EnforcementCommand;
import io.github.iy88.project1.casemanagement.application.EnforcementInstruction;
import io.github.iy88.project1.casemanagement.application.EnforcementOutcome;
import io.github.iy88.project1.casemanagement.application.ProductEnforcementPort;
import io.github.iy88.project1.casemanagement.application.SubjectCommand;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.application.SubjectResult;
import io.github.iy88.project1.casemanagement.application.TradeEnforcementPort;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.OssFileObjects.Location;
import io.github.iy88.project1.storage.content.FileContentVerifier.VerifiedContent;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ThreadLocalRandom;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import tools.jackson.databind.cfg.JsonNodeFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Real PostgreSQL/Spring transaction integration for the enforcement orchestrator. Subject
 * adapters are transaction-writing substitutes; file records and references use the real S1
 * file service. This test intentionally does not claim OSS upload coverage.
 */
class EnforcementIT {
    private static final UUID RUN_ID = UUID.randomUUID();
    private static final String FIXTURE_SCHEMA = "enforcement_it_" + RUN_ID.toString().replace("-", "");
    private static final UUID SESSION_ID = UUID.randomUUID();
    private static final long MANAGER_ID = ThreadLocalRandom.current().nextLong(1L << 42, 1L << 50);
    private static final long REPORTER_ID = MANAGER_ID + 1;
    private static final long PARTY_A = MANAGER_ID + 2;
    private static final long PARTY_B = MANAGER_ID + 3;
    private static final long OTHER_MANAGER_ID = MANAGER_ID + 4;
    private static final long CASE_ID = ThreadLocalRandom.current().nextLong(1L << 40, 1L << 45);
    private static final long PRODUCT_ID = CASE_ID + 1;
    private static final long TRADE_ID = CASE_ID + 2;
    private static final long REQUEST_ID = CASE_ID + 3;
    private static final long BASIS_ID = CASE_ID + 4;
    private static final long COMMENT_ID = CASE_ID + 5;
    private static final long EVALUATION_ID = CASE_ID + 6;
    private static final Instant OCCURRED_AT = Instant.parse("2026-01-01T00:00:00Z");
    private static final String OPERATION = "case.enforcement.batch";
    private static final LockPlan.Domain PRODUCT = LockPlan.Domain.PRODUCT;
    private static final LockPlan.Domain TRADE = LockPlan.Domain.TRADE;
    private static final LockPlan.Domain TRADE_CONVERSATION = LockPlan.Domain.TRADE_CONVERSATION;
    private static final LockPlan.Domain PRODUCT_DETAIL = LockPlan.Domain.PRODUCT_DETAIL;
    private static final LockPlan.Domain TRADE_DETAIL = LockPlan.Domain.TRADE_DETAIL;
    private static final LockPlan.Key PRODUCT_KEY = new LockPlan.Key(PRODUCT, List.of(PRODUCT_ID));
    private static final LockPlan.Key TRADE_KEY = new LockPlan.Key(TRADE, List.of(TRADE_ID));
    private static final LockPlan.Key CASE_KEY = new LockPlan.Key(LockPlan.Domain.CASE, List.of(CASE_ID));

    private static JdbcClient fixtureOwner;
    private static ConfigurableApplicationContext app;
    private static JdbcClient db;
    private static JsonMapper json;
    private static FileRegistry fileRegistry;
    private static FixtureSubjects subjects;
    private static EnforcementApplication enforcement;
    private static LockTrace trace;

    @BeforeAll
    static void startApplication() throws Exception {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        String baseNamespace = properties.getProperty("REDIS_NAMESPACE");
        if (baseNamespace == null || baseNamespace.isBlank()) {
            throw new IllegalArgumentException("REDIS_NAMESPACE is required");
        }
        properties.setProperty("REDIS_NAMESPACE", baseNamespace + ":enforcement:" + RUN_ID);
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "20");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        createFixtures(properties);
        // Use the same test pool and transaction for fixture rows and the real S1 tables.
        properties.setProperty("spring.datasource.hikari.connection-init-sql",
                "SET search_path TO " + FIXTURE_SCHEMA + ", public");
        properties.setProperty("spring.jpa.properties.hibernate.default_schema", "public");
        var application = new SpringApplication(BackendAppApplication.class, Fixtures.class);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource("enforcement-it", properties)));
        app = application.run("--spring.profiles.active=infrastructure", "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        db = app.getBean(JdbcClient.class);
        json = app.getBean(JsonMapper.class);
        fileRegistry = app.getBean(FileRegistry.class);
        subjects = app.getBean(FixtureSubjects.class);
        enforcement = app.getBean(EnforcementApplication.class);
        trace = app.getBean(LockTrace.class);
    }

    @AfterAll
    static void stopApplication() {
        try {
            if (app != null) {
                try (var context = app) {
                    cleanupInfrastructure();
                }
            }
        } finally {
            if (fixtureOwner != null) {
                fixtureOwner.sql("DROP SCHEMA IF EXISTS " + FIXTURE_SCHEMA + " CASCADE").update();
            }
        }
    }

    @BeforeEach
    void resetFixtures() {
        db.sql("""
                TRUNCATE enforcement_case_fixture, enforcement_case_evidence_fixture,
                    enforcement_execution_fixture, enforcement_subject_fixture, enforcement_scope_fixture
                """).update();
        cleanupInfrastructure();
        subjects.reset();
        trace.clear();
        db.sql("""
                INSERT INTO enforcement_case_fixture
                    (run_id, case_id, manager_id, target_type, target_id, basis_type, basis_id, archived)
                VALUES (?, ?, ?, 'product', ?, 'evidence', ?, FALSE)
                """).param(RUN_ID).param(CASE_ID).param(MANAGER_ID).param(PRODUCT_ID).param(BASIS_ID).update();
        insertSubject("account", MANAGER_ID, "ACTIVE");
        insertSubject("account", REPORTER_ID, "ACTIVE");
        insertSubject("account", PARTY_A, "ACTIVE");
        insertSubject("account", PARTY_B, "ACTIVE");
        insertSubject("product", PRODUCT_ID, "PUBLIC");
        insertSubject("trade", TRADE_ID, "ACTIVE");
        insertSubject("trade_request", REQUEST_ID, "PENDING");
        insertSubject("trade_conversation", TRADE_ID, "ACTIVE");
        insertSubject("trade_conversation", REQUEST_ID, "ACTIVE");
        insertSubject("product_detail", COMMENT_ID, "PUBLIC");
        insertSubject("trade_detail", EVALUATION_ID, "PUBLIC");
        insertScope(MANAGER_ID, PRODUCT_ID, TRADE_ID, REQUEST_ID);
        insertScope(PARTY_A, PRODUCT_ID, TRADE_ID, REQUEST_ID);
    }

    @Test
    void compositeFreezeAndWithdrawApplyAtomicallyRegardlessOfTargetOrder() {
        var first = enforcement.execute(context(MANAGER_ID), RUN_ID + "-composite-1", command(List.of(
                freeze("e1"), withdraw("e2")), List.of()));
        assertThat(first.replayed()).isFalse();
        assertThat(first.data().path("enforcements").size()).isEqualTo(2);
        assertThat(state("trade", TRADE_ID)).isEqualTo("FROZEN");
        assertThat(state("product", PRODUCT_ID)).isEqualTo("DISPLAY_WITHDRAWN");
        assertThat(trace.keys()).isSorted();
        assertThat(trace.keys()).doesNotHaveDuplicates();
        assertThat(auditCount(first.operationId())).isEqualTo(2);
        assertThat(executionCount()).isEqualTo(2);
        assertThat(eventCount(PARTY_A)).isEqualTo(2);
        assertThat(eventCount(PARTY_B)).isEqualTo(1);

        trace.clear();
        var second = enforcement.execute(context(MANAGER_ID), RUN_ID + "-composite-2", command(List.of(
                withdraw("e3"), freeze("e4")), List.of()));
        assertThat(second.replayed()).isFalse();
        assertThat(state("trade", TRADE_ID)).isEqualTo("FROZEN");
        assertThat(state("product", PRODUCT_ID)).isEqualTo("DISPLAY_WITHDRAWN");
        assertThat(trace.keys()).isSorted();
        assertThat(trace.keys()).doesNotHaveDuplicates();
        assertThat(trace.keys()).contains(PRODUCT_KEY, TRADE_KEY, CASE_KEY);
    }

    @Test
    void rollbackAfterSubjectAndFileWritesLeavesNoAuditOutboxReferenceOrIdempotencyState() {
        long fileId = verifiedFile(REPORTER_ID, FilePurpose.CASE_EVIDENCE);
        authorizeEvidence(fileId, REPORTER_ID, "evidence");
        String key = RUN_ID + "-rollback";
        var command = command(List.of(freeze("e1"), withdraw("e2")), List.of(fileId));
        subjects.failOn("e2");

        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), key, command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> {
                            assertThat(error.code()).isEqualTo("TARGET_STATE_CONFLICT");
                            assertThat(error.operationId()).isNotNull();
                            assertThat(auditCount(error.operationId())).isZero();
                        });

        assertThat(state("trade", TRADE_ID)).isEqualTo("ACTIVE");
        assertThat(state("product", PRODUCT_ID)).isEqualTo("PUBLIC");
        assertThat(fileReferenceCount(fileId)).isZero();
        assertThat(operationCount(key)).isZero();
        assertThat(executionCount()).isZero();
        assertThat(eventCount(PARTY_A)).isZero();

        subjects.clearFailures();
        var recovered = enforcement.execute(context(MANAGER_ID), key, command);
        assertThat(recovered.replayed()).isFalse();
        assertThat(state("trade", TRADE_ID)).isEqualTo("FROZEN");
        assertThat(state("product", PRODUCT_ID)).isEqualTo("DISPLAY_WITHDRAWN");
        assertThat(fileReferenceCount(fileId)).isEqualTo(1);
        assertThat(executionCount()).isEqualTo(2);
        assertThat(auditCount(recovered.operationId())).isEqualTo(2);
    }

    @Test
    void retriesTheWholeTransactionWhenAnActionDiscoversANewLockKey() {
        subjects.discoverAfterTrade("e1", PRODUCT_ID);
        var result = enforcement.execute(context(MANAGER_ID), RUN_ID + "-discover", command(List.of(
                freeze("e1")), List.of()));

        assertThat(state("trade", TRADE_ID)).isEqualTo("FROZEN");
        assertThat(trace.keys()).contains(PRODUCT_KEY, TRADE_KEY, CASE_KEY);
        assertThat(lastIndex(PRODUCT_KEY)).isLessThan(lastIndex(TRADE_KEY));
        assertThat(executionCount()).isEqualTo(1);
        assertThat(auditCount(result.operationId())).isEqualTo(1);
    }

    @Test
    void replaysUnchangedPayloadAndRejectsConflictingPayload() {
        String key = RUN_ID + "-replay";
        var command = command(List.of(withdraw("e1")), List.of());
        var first = enforcement.execute(context(MANAGER_ID), key, command);
        var replay = enforcement.execute(context(MANAGER_ID), key, command);

        assertThat(replay.replayed()).isTrue();
        assertThat(replay.operationId()).isEqualTo(first.operationId());
        assertThat(replay.data()).isEqualTo(json.readTree(first.data().toString()));
        assertThat(executionCount()).isEqualTo(1);
        assertThat(auditCount(first.operationId())).isEqualTo(1);

        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), key,
                command(List.of(withdraw("e1")), List.of(), "changed reason")))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("IDEMPOTENCY_PAYLOAD_CONFLICT"));

        trace.clear();
        var sameSource = enforcement.execute(context(MANAGER_ID), RUN_ID + "-replay-same-source", command);
        assertThat(sameSource.replayed()).isFalse();
        assertThat(sameSource.data().path("enforcements").get(0).path("status").asString()).isEqualTo("REPLAYED");
        assertThat(executionCount()).isEqualTo(1);
        assertThat(auditCount(first.operationId())).isEqualTo(1);
        assertThat(eventCount(PARTY_A)).isEqualTo(1);
        assertThat(trace.keys()).containsExactly(CASE_KEY);
    }

    @Test
    void rejectsChangedPayloadForPersistedExecutionIdWithoutChangingPriorOutcome() {
        String key = RUN_ID + "-payload-conflict";
        var command = command(List.of(withdraw("e1")), List.of());
        var first = enforcement.execute(context(MANAGER_ID), key, command);
        var original = execution("e1");
        assertThat(operationCount(key)).isEqualTo(1);

        trace.clear();
        String changedExpectedKey = RUN_ID + "-payload-conflict-expected";
        var changedExpected = new EnforcementInstruction("e1", EnforcementAction.WITHDRAW_PUBLIC_ACCESS,
                new ResourceRef("product", PRODUCT_ID), null, "unexpected");
        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), changedExpectedKey,
                command(List.of(changedExpected), List.of())))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("IDEMPOTENCY_PAYLOAD_CONFLICT");
                    assertThat(error.status()).isEqualTo(409);
                });
        assertPriorPayloadUnchanged(first.operationId(), original);
        assertThat(operationCount(changedExpectedKey)).isZero();
        assertThat(trace.keys()).containsExactly(CASE_KEY);

        trace.clear();
        String changedSharedKey = RUN_ID + "-payload-conflict-shared";
        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), changedSharedKey,
                command(List.of(withdraw("e1")), List.of(), "changed reason")))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("IDEMPOTENCY_PAYLOAD_CONFLICT");
                    assertThat(error.status()).isEqualTo(409);
                });
        assertPriorPayloadUnchanged(first.operationId(), original);
        assertThat(operationCount(changedSharedKey)).isZero();
        assertThat(trace.keys()).containsExactly(CASE_KEY);

        trace.clear();
        String changedBasisKey = RUN_ID + "-payload-conflict-basis";
        var changedBasis = new EnforcementCommand(CASE_ID, List.of(withdraw("e1")), List.of(BASIS_ID + 1),
                List.of(), "governance reason", OCCURRED_AT);
        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), changedBasisKey, changedBasis))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("IDEMPOTENCY_PAYLOAD_CONFLICT");
                    assertThat(error.status()).isEqualTo(409);
                });
        assertPriorPayloadUnchanged(first.operationId(), original);
        assertThat(operationCount(changedBasisKey)).isZero();
        assertThat(trace.keys()).containsExactly(CASE_KEY);
    }

    @Test
    void terminalAdjustmentAppendsTheSystemMessageBeforeArchiving() {
        var terminate = new EnforcementInstruction("terminal", EnforcementAction.ADJUST_TRADE_STATUS,
                new ResourceRef("trade", TRADE_ID), null, "terminated");
        enforcement.execute(context(MANAGER_ID), RUN_ID + "-terminal", command(List.of(terminate), List.of()));

        assertThat(state("trade", TRADE_ID)).isEqualTo("terminated");
        assertThat(state("trade_conversation", TRADE_ID)).isEqualTo("ARCHIVED");
    }

    @Test
    void rejectsUnauthorizedManagementAndRevokedReplay() {
        var command = command(List.of(withdraw("e1")), List.of());
        assertThatThrownBy(() -> enforcement.execute(context(OTHER_MANAGER_ID), RUN_ID + "-unauthorized", command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("NOT_CASE_MANAGER"));

        String key = RUN_ID + "-revoked";
        enforcement.execute(context(MANAGER_ID), key, command);
        db.sql("UPDATE enforcement_case_fixture SET manager_id = ? WHERE run_id = ? AND case_id = ?")
                .param(OTHER_MANAGER_ID).param(RUN_ID).param(CASE_ID).update();

        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), key, command))
                .isInstanceOfSatisfying(BusinessError.class,
                        error -> assertThat(error.code()).isEqualTo("NOT_CASE_MANAGER"));
    }

    @Test
    void distinguishesVerifiedPendingWrongPurposeWrongOwnerAndUnauthorizedEvidence() {
        long pending = pendingFile(REPORTER_ID, FilePurpose.CASE_EVIDENCE);
        authorizeEvidence(pending, REPORTER_ID, "evidence");
        assertEvidenceFailure(pending, "e-pending", "FILE_NOT_REFERENCEABLE", 422);

        long wrongPurpose = verifiedFile(REPORTER_ID, FilePurpose.PRODUCT_IMAGE);
        authorizeEvidence(wrongPurpose, REPORTER_ID, "evidence");
        assertEvidenceFailure(wrongPurpose, "e-purpose", "FILE_PURPOSE_MISMATCH", 422);

        long wrongOwner = verifiedFile(PARTY_B, FilePurpose.CASE_EVIDENCE);
        authorizeEvidence(wrongOwner, REPORTER_ID, "evidence");
        assertEvidenceFailure(wrongOwner, "e-owner", "RESOURCE_NOT_VISIBLE", 404);

        long unauthorized = verifiedFile(REPORTER_ID, FilePurpose.CASE_EVIDENCE);
        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID), RUN_ID + "-evidence-unauthorized",
                command(List.of(withdraw("e-unauthorized")), List.of(unauthorized))))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo("EVIDENCE_OUT_OF_SCOPE");
                    assertThat(error.status()).isEqualTo(422);
                });
        assertThat(fileReferenceCount(unauthorized)).isZero();

        long verified = verifiedFile(REPORTER_ID, FilePurpose.CASE_EVIDENCE);
        authorizeEvidence(verified, REPORTER_ID, "evidence");
        var success = enforcement.execute(context(MANAGER_ID), RUN_ID + "-evidence-ok",
                command(List.of(withdraw("ok")), List.of(verified)));
        assertThat(success.replayed()).isFalse();
        assertThat(fileReferenceCount(verified)).isEqualTo(1);
        assertThat(fileReferenceTarget(verified)).isEqualTo(new FileTarget("case", CASE_ID));
        assertThat(fileReferenceCreator(verified)).isEqualTo(Long.toString(REPORTER_ID));
    }

    @Test
    void accountRestrictionLiftRestoresOnlyTheSpecifiedSourceAndDoesNotListAnOffShelfProduct() {
        var restricted = enforcement.execute(context(MANAGER_ID), RUN_ID + "-restrict", command(List.of(
                new EnforcementInstruction("r1", EnforcementAction.RESTRICT_ACCOUNT,
                        new ResourceRef("account", MANAGER_ID), null, null)), List.of()));
        assertThat(state("account", MANAGER_ID)).isEqualTo("RESTRICTED");
        assertThat(state("product", PRODUCT_ID)).isEqualTo("DISPLAY_RESTRICTED");
        assertThat(state("trade", TRADE_ID)).isEqualTo("FROZEN");
        assertThat(state("trade_request", REQUEST_ID)).isEqualTo("CLOSED");
        assertThat(state("trade_conversation", REQUEST_ID)).isEqualTo("ARCHIVED");

        long restrictionId = restricted.data().path("enforcements").get(0).path("result").path("id").asLong();
        var lift = new EnforcementInstruction("l1", EnforcementAction.LIFT_ACCOUNT_RESTRICTION,
                new ResourceRef("account", MANAGER_ID), new ResourceRef("account_restriction", restrictionId), null);
        var lifted = enforcement.execute(context(MANAGER_ID), RUN_ID + "-lift", command(List.of(lift), List.of()));
        assertThat(lifted.replayed()).isFalse();
        assertThat(state("account", MANAGER_ID)).isEqualTo("ACTIVE");
        assertThat(state("product", PRODUCT_ID)).isEqualTo("OFF_SHELF");
        assertThat(state("trade", TRADE_ID)).isEqualTo("ACTIVE");

        var replay = enforcement.execute(context(MANAGER_ID), RUN_ID + "-lift", command(List.of(lift), List.of()));
        assertThat(replay.replayed()).isTrue();
        assertThat(executionCount()).isEqualTo(2);
    }

    private static void assertEvidenceFailure(long fileId, String enforcementId, String code, int status) {
        assertThatThrownBy(() -> enforcement.execute(context(MANAGER_ID),
                RUN_ID + "-evidence-" + enforcementId, command(List.of(withdraw(enforcementId)), List.of(fileId))))
                .isInstanceOfSatisfying(BusinessError.class, error -> {
                    assertThat(error.code()).isEqualTo(code);
                    assertThat(error.status()).isEqualTo(status);
                });
        assertThat(fileReferenceCount(fileId)).isZero();
        assertThat(executionCount()).isZero();
    }

    private static void assertPriorPayloadUnchanged(UUID operationId, ExecutionSnapshot original) {
        assertThat(state("product", PRODUCT_ID)).isEqualTo("DISPLAY_WITHDRAWN");
        assertThat(executionCount()).isEqualTo(1);
        assertThat(execution("e1")).isEqualTo(original);
        assertThat(auditCount(operationId)).isEqualTo(1);
        assertThat(eventCount(PARTY_A)).isEqualTo(1);
        assertThat(eventCount(PARTY_B)).isZero();
    }

    private static EnforcementCommand command(List<EnforcementInstruction> enforcements, List<Long> evidence) {
        return command(enforcements, evidence, "governance reason");
    }

    private static EnforcementCommand command(List<EnforcementInstruction> enforcements, List<Long> evidence,
                                              String reason) {
        return new EnforcementCommand(CASE_ID, enforcements, List.of(BASIS_ID), evidence, reason, OCCURRED_AT);
    }

    private static EnforcementInstruction freeze(String id) {
        return EnforcementInstruction.of(id, EnforcementAction.FREEZE_TRADE, new ResourceRef("trade", TRADE_ID));
    }

    private static EnforcementInstruction withdraw(String id) {
        return EnforcementInstruction.of(id, EnforcementAction.WITHDRAW_PUBLIC_ACCESS,
                new ResourceRef("product", PRODUCT_ID));
    }

    private static ExecutionContext context(long accountId) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT, Long.toString(accountId),
                SESSION_ID, null, 1L, "enforcement-it");
    }

    private static int lastIndex(LockPlan.Key key) {
        var keys = trace.keys();
        return keys.lastIndexOf(key);
    }

    private static void createFixtures(Properties properties) throws SQLException {
        var source = new DriverManagerDataSource(properties.getProperty("DATABASE_URL"),
                properties.getProperty("DATABASE_OWNER_USERNAME"), properties.getProperty("DATABASE_OWNER_PASSWORD"));
        fixtureOwner = JdbcClient.create(source);
        fixtureOwner.sql("CREATE SCHEMA " + FIXTURE_SCHEMA).update();
        try (var connection = source.getConnection(); var statement = connection.createStatement()) {
            statement.execute("SET search_path TO " + FIXTURE_SCHEMA);
            new ResourceDatabasePopulator(new ClassPathResource("integration/enforcement-fixtures.sql"))
                    .populate(connection);
        }
        String role = fixtureOwner.sql("SELECT quote_ident(?)").param(properties.getProperty("DATABASE_USERNAME"))
                .query(String.class).single();
        fixtureOwner.sql("GRANT USAGE ON SCHEMA " + FIXTURE_SCHEMA + " TO " + role).update();
        fixtureOwner.sql("GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA "
                + FIXTURE_SCHEMA + " TO " + role).update();
    }

    private static void cleanupInfrastructure() {
        db.sql("DELETE FROM file_reference WHERE file_id IN (SELECT file_id FROM file_record WHERE object_key LIKE ?)")
                .param("it-enforcement-" + RUN_ID + "%").update();
        db.sql("DELETE FROM file_record WHERE object_key LIKE ?").param("it-enforcement-" + RUN_ID + "%").update();
        db.sql("DELETE FROM user_event WHERE recipient_account_id IN (?, ?, ?, ?)")
                .param(MANAGER_ID).param(REPORTER_ID).param(PARTY_A).param(PARTY_B).update();
        db.sql("DELETE FROM account_event_head WHERE account_id IN (?, ?, ?, ?)")
                .param(MANAGER_ID).param(REPORTER_ID).param(PARTY_A).param(PARTY_B).update();
        db.sql("DELETE FROM operation_record WHERE actor_id IN (?, ?, ?, ?)")
                .param(Long.toString(MANAGER_ID)).param(Long.toString(REPORTER_ID))
                .param(Long.toString(PARTY_A)).param(Long.toString(OTHER_MANAGER_ID)).update();
        db.sql("DELETE FROM audit_record WHERE actor_id IN (?, ?, ?, ?)")
                .param(Long.toString(MANAGER_ID)).param(Long.toString(REPORTER_ID))
                .param(Long.toString(PARTY_A)).param(Long.toString(OTHER_MANAGER_ID)).update();
    }

    private static void insertSubject(String subject, long id, String state) {
        db.sql("""
                INSERT INTO enforcement_subject_fixture (run_id, subject, subject_id, state)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (run_id, subject, subject_id)
                DO UPDATE SET state = EXCLUDED.state, source_ref = NULL, updated_at = statement_timestamp()
                """).param(RUN_ID).param(subject).param(id).param(state).update();
    }

    private static void insertScope(long accountId, long productId, long tradeId, long requestId) {
        db.sql("""
                INSERT INTO enforcement_scope_fixture (run_id, account_id, product_id, trade_id, request_id)
                VALUES (?, ?, ?, ?, ?)
                """).param(RUN_ID).param(accountId).param(productId).param(tradeId).param(requestId).update();
    }

    private static void authorizeEvidence(long fileId, long submittedBy, String slot) {
        db.sql("""
                INSERT INTO enforcement_case_evidence_fixture (run_id, case_id, file_id, submitted_by, slot)
                VALUES (?, ?, ?, ?, ?)
                """).param(RUN_ID).param(CASE_ID).param(fileId).param(submittedBy).param(slot).update();
    }

    private static long verifiedFile(long owner, FilePurpose purpose) {
        long fileId = registerFile(owner, purpose);
        fileRegistry.markVerified(fileId, owner, "\"it-" + fileId + "\"", new VerifiedContent(8, "image/png"));
        return fileId;
    }

    private static long pendingFile(long owner, FilePurpose purpose) {
        return registerFile(owner, purpose);
    }

    private static long registerFile(long owner, FilePurpose purpose) {
        var now = Instant.now();
        var key = "it-enforcement-" + RUN_ID + "-" + UUID.randomUUID();
        var entry = fileRegistry.register(new UploadRegistration.Draft(owner, purpose, null,
                new Location("it-bucket", key), 8, "image/png", "it",
                now.minusSeconds(5), now.plusSeconds(60), now.plusSeconds(120)));
        return entry.fileId();
    }

    private static String state(String subject, long id) {
        return db.sql("SELECT state FROM enforcement_subject_fixture WHERE run_id = ? AND subject = ? AND subject_id = ?")
                .param(RUN_ID).param(subject).param(id).query(String.class).single();
    }

    private static long executionCount() {
        return db.sql("SELECT count(*) FROM enforcement_execution_fixture WHERE run_id = ? AND case_id = ?")
                .param(RUN_ID).param(CASE_ID).query(Long.class).single();
    }

    private static ExecutionSnapshot execution(String enforcementId) {
        return db.sql("""
                SELECT action, target_type, target_id, result_type, result_id, previous_state, current_state,
                       occurred_at, status
                FROM enforcement_execution_fixture
                WHERE run_id = ? AND case_id = ? AND enforcement_id = ?
                """).param(RUN_ID).param(CASE_ID).param(enforcementId)
                .query((row, index) -> new ExecutionSnapshot(row.getString("action"),
                        row.getString("target_type"), row.getLong("target_id"),
                        row.getString("result_type"), row.getLong("result_id"),
                        row.getString("previous_state"), row.getString("current_state"),
                        row.getTimestamp("occurred_at").toInstant(), row.getString("status")))
                .single();
    }

    private static long fileReferenceCount(long fileId) {
        return db.sql("SELECT count(*) FROM file_reference WHERE file_id = ? AND target_type = 'case' AND target_id = ?")
                .param(fileId).param(CASE_ID).query(Long.class).single();
    }

    private static FileTarget fileReferenceTarget(long fileId) {
        return db.sql("SELECT target_type, target_id FROM file_reference WHERE file_id = ? AND target_type = 'case' AND target_id = ?")
                .param(fileId).param(CASE_ID).query((row, index) ->
                        new FileTarget(row.getString("target_type"), row.getLong("target_id"))).single();
    }

    private static String fileReferenceCreator(long fileId) {
        return db.sql("SELECT created_by FROM file_reference WHERE file_id = ? AND target_type = 'case' AND target_id = ?")
                .param(fileId).param(CASE_ID).query(String.class).single();
    }

    private static long operationCount(String key) {
        return db.sql("SELECT count(*) FROM operation_record WHERE actor_id = ? AND operation_name = ? AND idempotency_key = ?")
                .param(Long.toString(MANAGER_ID)).param(OPERATION).param(key).query(Long.class).single();
    }

    private static long auditCount(UUID operationId) {
        return db.sql("SELECT count(*) FROM audit_record WHERE operation_id = ?").param(operationId)
                .query(Long.class).single();
    }

    private static long eventCount(long recipient) {
        return db.sql("SELECT count(*) FROM user_event WHERE recipient_account_id = ?").param(recipient)
                .query(Long.class).single();
    }

    private record FileTarget(String type, long id) {}

    private record ExecutionSnapshot(String action, String targetType, long targetId, String resultType,
                                     long resultId, String previousState, String currentState,
                                     Instant occurredAt, String status) {}

    static final class LockTrace {
        private final List<LockPlan.Key> keys = new CopyOnWriteArrayList<>();

        void add(LockPlan.Key key) {
            keys.add(key);
        }

        List<LockPlan.Key> keys() {
            return List.copyOf(keys);
        }

        void clear() {
            keys.clear();
        }
    }

    static final class FixtureCases implements CaseEnforcementPort {
        private static final JsonMapper CANONICAL = JsonMapper.builder()
                .enable(JsonNodeFeature.WRITE_PROPERTIES_SORTED, JsonNodeFeature.USE_BIG_DECIMAL_FOR_FLOATS)
                .build();
        private final JdbcClient db;
        private final LockTrace trace;

        FixtureCases(JdbcClient db, LockTrace trace) {
            this.db = db;
            this.trace = trace;
        }

        @Override
        public CaseAccess prepare(ExecutionContext context, EnforcementCommand command) {
            return load(context, command);
        }

        @Override
        public CaseAccess requireManager(ExecutionContext context, EnforcementCommand command) {
            return load(context, command);
        }

        @Override
        public CaseAccess revalidate(WriteTransaction transaction, ExecutionContext context,
                                     EnforcementCommand command, CaseAccess current) {
            var access = load(context, command);
            // The coordinator already holds the CASE row lock. Compare only the current
            // instruction with its own persisted request before allowing its outcome to replay.
            for (var instruction : command.enforcements()) {
                var original = db.sql("""
                        SELECT request_payload FROM enforcement_execution_fixture
                        WHERE run_id = ? AND case_id = ? AND enforcement_id = ?
                        """).param(RUN_ID).param(command.caseId()).param(instruction.enforcementId())
                        .query(String.class).optional();
                if (original.isPresent() && !original.get().equals(payload(command, instruction))) {
                    throw new BusinessError("IDEMPOTENCY_PAYLOAD_CONFLICT", 409,
                            "execution id already used with another payload");
                }
            }
            return access;
        }

        @Override
        public void requireExecutable(WriteTransaction transaction, ExecutionContext context,
                                      EnforcementCommand command, CaseAccess access) {
            var archived = db.sql("SELECT archived FROM enforcement_case_fixture WHERE run_id = ? AND case_id = ?")
                    .param(RUN_ID).param(CASE_ID).query(Boolean.class).single();
            if (archived) {
                throw new BusinessError("CASE_CLOSED", 409, "case closed");
            }
            if (!command.basisRefs().equals(access.basis().stream().map(ResourceRef::id).toList())) {
                throw new BusinessError("EVIDENCE_OUT_OF_SCOPE", 422, "basis is outside this case");
            }
        }

        @Override
        public void lockCase(WriteTransaction transaction, long caseId) {
            trace.add(new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId)));
            var found = db.sql("""
                    SELECT case_id FROM enforcement_case_fixture
                    WHERE run_id = ? AND case_id = ? FOR UPDATE
                    """).param(RUN_ID).param(caseId).query(Long.class).optional();
            if (found.isEmpty()) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "case not visible");
            }
        }

        @Override
        public void recordExecution(WriteTransaction transaction, ExecutionContext context,
                                    EnforcementCommand command, List<EnforcementOutcome> outcomes,
                                    List<FileReferences.Reference> references) {
            var instructions = new java.util.HashMap<String, EnforcementInstruction>();
            command.enforcements().forEach(instruction -> instructions.put(instruction.enforcementId(), instruction));
            for (var outcome : outcomes) {
                var instruction = instructions.get(outcome.enforcementId());
                if (instruction == null) {
                    throw new IllegalStateException("Missing instruction for " + outcome.enforcementId());
                }
                db.sql("""
                        INSERT INTO enforcement_execution_fixture
                            (run_id, case_id, enforcement_id, action, target_type, target_id,
                             result_type, result_id, previous_state, current_state, occurred_at, status,
                             request_payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """).param(RUN_ID).param(CASE_ID).param(outcome.enforcementId())
                        .param(outcome.action().name()).param(outcome.target().type()).param(outcome.target().id())
                        .param(outcome.result().type()).param(outcome.result().id())
                        .param(outcome.previousState()).param(outcome.currentState())
                        .param(java.sql.Timestamp.from(outcome.occurredAt())).param(outcome.status().name())
                        .param(payload(command, instruction)).update();
            }
        }

        /**
         * Canonical view of one original execution request. Occurred time, the outer HTTP
         * idempotency key, derived outcomes and sibling instructions are intentionally excluded.
         */
        private static String payload(EnforcementCommand command, EnforcementInstruction instruction) {
            var root = CANONICAL.createObjectNode();
            root.put("case_id", command.caseId());
            root.put("enforcement_id", instruction.enforcementId());
            root.put("action", instruction.action().name());
            var target = root.putObject("target");
            target.put("type", instruction.target().type());
            target.put("id", instruction.target().id());
            if (instruction.detail() != null) {
                var detail = root.putObject("detail");
                detail.put("type", instruction.detail().type());
                detail.put("id", instruction.detail().id());
            }
            if (instruction.expectedResult() != null) {
                root.put("expected_result", instruction.expectedResult());
            }
            var basis = root.putArray("basis_refs");
            command.basisRefs().forEach(basis::add);
            var evidence = root.putArray("evidence_file_ids");
            command.evidenceFileIds().forEach(evidence::add);
            root.put("reason", command.reason());
            return CANONICAL.writeValueAsString(root);
        }

        @Override
        public void requireReplayAccess(ExecutionContext context, long caseId) {
            var manager = db.sql("SELECT manager_id FROM enforcement_case_fixture WHERE run_id = ? AND case_id = ?")
                    .param(RUN_ID).param(caseId).query(Long.class).optional();
            if (manager.isEmpty()) {
                throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "case not visible");
            }
            if (manager.get() != Long.parseLong(context.actorId())) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "not case manager");
            }
        }

        @Override
        public void recordFailure(ExecutionContext context, EnforcementCommand command,
                                  String errorCode, String message) {
            throw new AssertionError("The caller-owned failure trail is outside this integration fixture");
        }

        private CaseAccess load(ExecutionContext context, EnforcementCommand command) {
            var manager = db.sql("SELECT manager_id FROM enforcement_case_fixture WHERE run_id = ? AND case_id = ?")
                    .param(RUN_ID).param(CASE_ID).query(Long.class).optional()
                    .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "case not visible"));
            if (manager != Long.parseLong(context.actorId())) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "not case manager");
            }
            var target = db.sql("""
                    SELECT target_type, target_id FROM enforcement_case_fixture WHERE run_id = ? AND case_id = ?
                    """).param(RUN_ID).param(CASE_ID).query((row, index) ->
                    new ResourceRef(row.getString("target_type"), row.getLong("target_id"))).single();
            var basis = db.sql("""
                    SELECT basis_type, basis_id FROM enforcement_case_fixture WHERE run_id = ? AND case_id = ?
                    """).param(RUN_ID).param(CASE_ID).query((row, index) ->
                    new ResourceRef(row.getString("basis_type"), row.getLong("basis_id"))).single();
            Set<Long> authorized = new HashSet<>(command.evidenceFileIds());
            var evidence = db.sql("""
                    SELECT file_id, submitted_by, slot FROM enforcement_case_evidence_fixture
                    WHERE run_id = ? AND case_id = ? ORDER BY file_id
                    """).param(RUN_ID).param(CASE_ID).query((row, index) ->
                    new CaseEvidence(row.getLong("file_id"), row.getLong("submitted_by"), row.getString("slot")))
                    .list().stream().filter(item -> authorized.contains(item.fileId())).toList();
            Map<String, EnforcementOutcome> prior = new java.util.LinkedHashMap<>();
            db.sql("""
                    SELECT enforcement_id, action, target_type, target_id, result_type, result_id,
                           previous_state, current_state, occurred_at, status
                    FROM enforcement_execution_fixture WHERE run_id = ? AND case_id = ? ORDER BY enforcement_id
                    """).param(RUN_ID).param(CASE_ID).query((row, index) -> {
                var outcome = new EnforcementOutcome(row.getString("enforcement_id"),
                        EnforcementAction.valueOf(row.getString("action")),
                        new ResourceRef(row.getString("target_type"), row.getLong("target_id")),
                        new ResourceRef(row.getString("result_type"), row.getLong("result_id")),
                        row.getString("previous_state"), row.getString("current_state"), List.of(),
                        row.getTimestamp("occurred_at").toInstant(),
                        EnforcementOutcome.Status.valueOf(row.getString("status")));
                prior.put(outcome.enforcementId(), outcome);
                return outcome;
            }).list();
            return new CaseAccess(CASE_ID, manager, REPORTER_ID, target, List.of(basis), evidence, prior,
                    Set.of(manager, REPORTER_ID, PARTY_A, PARTY_B));
        }
    }

    static final class FixtureSubjects implements AccountEnforcementPort, ProductEnforcementPort,
            TradeEnforcementPort, ConversationEnforcementPort {
        private final JdbcClient db;
        private final LockTrace trace;
        private final Set<String> failures = new HashSet<>();
        private final Map<String, Long> discovered = new java.util.HashMap<>();
        private final Map<String, Long> pendingDiscoveries = new java.util.HashMap<>();

        FixtureSubjects(JdbcClient db, LockTrace trace) {
            this.db = db;
            this.trace = trace;
        }

        void reset() {
            failures.clear();
            discovered.clear();
            pendingDiscoveries.clear();
        }

        void failOn(String enforcementId) {
            failures.add(enforcementId);
        }

        void clearFailures() {
            failures.clear();
        }

        void discoverAfterTrade(String enforcementId, long productId) {
            pendingDiscoveries.put(enforcementId, productId);
        }

        @Override
        public SubjectPlan prepare(SubjectCommand command) {
            var plan = SubjectPlan.empty();
            switch (command.action()) {
                case RESTRICT_ACCOUNT, LIFT_ACCOUNT_RESTRICTION -> {
                    plan = plan.merge(SubjectPlan.account(command.target().id(), LockPlan.AccountMode.EXCLUSIVE));
                    plan = plan.merge(SubjectPlan.account(PARTY_A, LockPlan.AccountMode.SHARED));
                    plan = plan.merge(SubjectPlan.account(PARTY_B, LockPlan.AccountMode.SHARED));
                    for (var scope : scopesForAccount(command.target().id())) {
                        plan = plan.merge(subject(PRODUCT, scope.productId, "product"));
                        plan = plan.merge(subject(TRADE, scope.tradeId, "trade"));
                        plan = plan.merge(subject(TRADE, scope.requestId, "trade_request"));
                        plan = plan.merge(subject(TRADE_CONVERSATION, scope.requestId, "trade_conversation"));
                    }
                }
                case WITHDRAW_PUBLIC_ACCESS -> {
                    plan = plan.merge(SubjectPlan.account(PARTY_A, LockPlan.AccountMode.SHARED));
                    plan = plan.merge(subject(PRODUCT, command.target().id(), "product"));
                    for (var scope : scopesForProduct(command.target().id())) {
                        plan = plan.merge(subject(TRADE, scope.requestId, "trade_request"));
                        plan = plan.merge(subject(TRADE_CONVERSATION, scope.requestId, "trade_conversation"));
                    }
                }
                case RESTORE_DISPLAY -> {
                    plan = plan.merge(SubjectPlan.account(PARTY_A, LockPlan.AccountMode.SHARED));
                    plan = plan.merge(subject(PRODUCT, command.target().id(), "product"));
                }
                case REMOVE_CONTENT -> {
                    plan = plan.merge(SubjectPlan.account(PARTY_A, LockPlan.AccountMode.SHARED));
                    plan = "comment".equals(command.target().type())
                            ? plan.merge(subject(PRODUCT_DETAIL, command.target().id(), "product_detail"))
                            : plan.merge(subject(TRADE_DETAIL, command.target().id(), "trade_detail"));
                }
                case FREEZE_TRADE, LIFT_TRADE_FREEZE, ADJUST_TRADE_STATUS -> {
                    plan = plan.merge(SubjectPlan.account(PARTY_A, LockPlan.AccountMode.SHARED));
                    plan = plan.merge(SubjectPlan.account(PARTY_B, LockPlan.AccountMode.SHARED));
                    plan = plan.merge(subject(TRADE, command.target().id(), "trade"));
                    plan = plan.merge(subject(TRADE_CONVERSATION, command.target().id(), "trade_conversation"));
                }
                case REMOVE_EVALUATION_CONTENT -> {
                    plan = plan.merge(SubjectPlan.account(PARTY_A, LockPlan.AccountMode.SHARED));
                    plan = plan.merge(subject(TRADE_DETAIL, command.target().id(), "trade_detail"));
                }
            }
            Long discoveredProduct = discovered.get(command.enforcementId());
            if (discoveredProduct != null) {
                plan = plan.merge(subject(PRODUCT, discoveredProduct, "product"));
            }
            return plan;
        }

        @Override
        public Restriction restrict(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            var scope = scopesForAccount(command.target().id());
            var restriction = new ResourceRef("account_restriction", stableId(command));
            boolean already = "RESTRICTED".equals(current("account", command.target().id()));
            write("account", command.target().id(), "RESTRICTED", restriction.id());
            var products = scope.stream().map(item -> new ResourceRef("product", item.productId)).toList();
            var trades = scope.stream().map(item -> new ResourceRef("trade", item.tradeId)).toList();
            var requests = scope.stream().map(item -> new ResourceRef("trade_request", item.requestId)).toList();
            var affected = new ArrayList<ResourceRef>();
            affected.addAll(products);
            affected.addAll(trades);
            affected.addAll(requests);
            return new Restriction(new SubjectResult(restriction, "ACTIVE", "RESTRICTED", affected,
                    Set.of(command.target().id()), already), restriction, products, trades, requests);
        }

        @Override
        public Release lift(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            var scope = scopesForAccount(command.target().id());
            var restriction = command.detail();
            boolean already = "ACTIVE".equals(current("account", command.target().id()));
            write("account", command.target().id(), "ACTIVE", restriction.id());
            var products = scope.stream().map(item -> new ResourceRef("product", item.productId)).toList();
            return new Release(new SubjectResult(restriction, "RESTRICTED", "ACTIVE", products,
                    Set.of(command.target().id()), already), restriction, products);
        }

        @Override
        public Withdrawal withdraw(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            boolean already = "DISPLAY_WITHDRAWN".equals(current("product", command.target().id()));
            write("product", command.target().id(), "DISPLAY_WITHDRAWN", command.target().id());
            var requests = scopesForProduct(command.target().id()).stream()
                    .map(item -> new ResourceRef("trade_request", item.requestId)).toList();
            return new Withdrawal(new SubjectResult(
                    new ResourceRef("product_display_restriction", stableId(command)), "PUBLIC", "DISPLAY_WITHDRAWN",
                    requests, Set.of(PARTY_A), already), requests);
        }

        @Override
        public SubjectResult restore(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            boolean already = "PUBLIC".equals(current("product", command.target().id()));
            write("product", command.target().id(), "PUBLIC", command.target().id());
            return new SubjectResult(new ResourceRef("product_display_restriction", stableId(command)),
                    "DISPLAY_WITHDRAWN", "PUBLIC", List.of(), Set.of(PARTY_A), already);
        }

        @Override
        public SubjectResult removeContent(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            boolean already = "REMOVED".equals(current("product_detail", command.target().id()));
            write("product_detail", command.target().id(), "REMOVED", command.target().id());
            return new SubjectResult(command.target(), "PUBLIC", "REMOVED", List.of(), Set.of(REPORTER_ID), already);
        }

        @Override
        public SubjectResult restrictForAccount(WriteTransaction transaction, SubjectCommand command,
                                                ResourceRef restrictionRef, List<ResourceRef> products) {
            for (var product : products) {
                write("product", product.id(), "DISPLAY_RESTRICTED", restrictionRef.id());
            }
            return new SubjectResult(new ResourceRef("product_display_restriction", restrictionRef.id()), "PUBLIC",
                    "DISPLAY_RESTRICTED", products, Set.of(PARTY_A), false);
        }

        @Override
        public SubjectResult restoreForAccount(WriteTransaction transaction, SubjectCommand command,
                                               ResourceRef restrictionRef, List<ResourceRef> products) {
            for (var product : products) {
                write("product", product.id(), "OFF_SHELF", restrictionRef.id());
            }
            return new SubjectResult(new ResourceRef("product_display_restriction", restrictionRef.id()),
                    "DISPLAY_RESTRICTED", "OFF_SHELF", products, Set.of(PARTY_A), false);
        }

        @Override
        public SubjectResult freeze(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            Long productId = pendingDiscoveries.remove(command.enforcementId());
            boolean already = "FROZEN".equals(current("trade", command.target().id()));
            write("trade", command.target().id(), "FROZEN", command.target().id());
            if (productId != null) {
                discovered.put(command.enforcementId(), productId);
                throw new LockPlan.Changed(new LockPlan(Map.of(), Set.of(
                        new LockPlan.Key(PRODUCT, List.of(productId)))));
            }
            return new SubjectResult(new ResourceRef("trade_transition", stableId(command)), "ACTIVE", "FROZEN",
                    List.of(), Set.of(PARTY_A, PARTY_B), already);
        }

        @Override
        public SubjectResult liftFreeze(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            boolean already = "ACTIVE".equals(current("trade", command.target().id()));
            write("trade", command.target().id(), "ACTIVE", command.target().id());
            return new SubjectResult(new ResourceRef("trade_transition", stableId(command)), "FROZEN", "ACTIVE",
                    List.of(), Set.of(PARTY_A, PARTY_B), already);
        }

        @Override
        public Adjustment adjustStatus(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            String target = command.expectedResult();
            boolean terminal = "completed".equals(target) || "terminated".equals(target);
            boolean already = target.equals(current("trade", command.target().id()));
            write("trade", command.target().id(), target, command.target().id());
            return new Adjustment(new SubjectResult(new ResourceRef("trade_transition", stableId(command)),
                    "ACTIVE", target, List.of(), Set.of(PARTY_A, PARTY_B), already),
                    terminal ? "trade_" + target : "trade_restored", terminal);
        }

        @Override
        public SubjectResult closeRequests(WriteTransaction transaction, SubjectCommand command,
                                           List<ResourceRef> requestRefs) {
            for (var request : requestRefs) {
                write("trade_request", request.id(), "CLOSED", command.target().id());
            }
            return new SubjectResult(command.target(), "PENDING", "CLOSED", requestRefs, Set.of(), false);
        }

        @Override
        public SubjectResult freezeForAccount(WriteTransaction transaction, SubjectCommand command,
                                              ResourceRef restrictionRef, List<ResourceRef> trades) {
            for (var trade : trades) {
                write("trade", trade.id(), "FROZEN", restrictionRef.id());
            }
            return new SubjectResult(trades.isEmpty() ? command.target() : trades.getFirst(), "ACTIVE", "FROZEN",
                    trades, Set.of(PARTY_A, PARTY_B), false);
        }

        @Override
        public SubjectResult liftAccountFreeze(WriteTransaction transaction, SubjectCommand command,
                                              ResourceRef restrictionRef) {
            var restored = new ArrayList<ResourceRef>();
            for (var scope : scopesForAccount(command.target().id())) {
                int changed = db.sql("""
                        UPDATE enforcement_subject_fixture SET state = 'ACTIVE', source_ref = NULL
                        WHERE run_id = ? AND subject = 'trade' AND subject_id = ? AND source_ref = ?
                        """).param(RUN_ID).param(scope.tradeId()).param(Long.toString(restrictionRef.id())).update();
                if (changed == 1) {
                    restored.add(new ResourceRef("trade", scope.tradeId()));
                }
            }
            return SubjectResult.of(restrictionRef, "FROZEN", "ACTIVE").withAffectedScope(restored);
        }

        @Override
        public SubjectResult removeEvaluation(WriteTransaction transaction, SubjectCommand command) {
            maybeFail(command);
            boolean already = "REMOVED".equals(current("trade_detail", command.target().id()));
            write("trade_detail", command.target().id(), "REMOVED", command.target().id());
            return new SubjectResult(command.target(), "PUBLIC", "REMOVED", List.of(), Set.of(REPORTER_ID), already);
        }

        @Override
        public SubjectResult appendTradeEvent(WriteTransaction transaction, SubjectCommand command,
                                              String eventType, ResourceRef sourceRef) {
            write("trade_conversation", command.target().id(), eventType, sourceRef.id());
            return new SubjectResult(new ResourceRef("trade_message", stableId(command)), "ACTIVE", eventType,
                    List.of(), Set.of(), false);
        }

        @Override
        public SubjectResult archiveTradeConversation(WriteTransaction transaction, SubjectCommand command,
                                                      ResourceRef sourceRef) {
            assertThat(current("trade_conversation", command.target().id()))
                    .isIn("trade_completed", "trade_terminated");
            write("trade_conversation", command.target().id(), "ARCHIVED", sourceRef.id());
            return new SubjectResult(new ResourceRef("trade_conversation", command.target().id()), "ACTIVE",
                    "ARCHIVED", List.of(), Set.of(), false);
        }

        @Override
        public SubjectResult archiveRequestBranches(WriteTransaction transaction, SubjectCommand command,
                                                    List<ResourceRef> requestRefs) {
            for (var request : requestRefs) {
                write("trade_conversation", request.id(), "ARCHIVED", command.target().id());
            }
            return new SubjectResult(requestRefs.isEmpty() ? command.target() : requestRefs.getFirst(), "ACTIVE",
                    "ARCHIVED", requestRefs, Set.of(), false);
        }

        private SubjectPlan subject(LockPlan.Domain domain, long id, String subject) {
            var key = new LockPlan.Key(domain, List.of(id));
            return SubjectPlan.resource(key, transaction -> {
                trace.add(key);
                db.sql("""
                        SELECT 1 FROM enforcement_subject_fixture
                        WHERE run_id = ? AND subject = ? AND subject_id = ? FOR UPDATE
                        """).param(RUN_ID).param(subject).param(id).query(Integer.class).optional();
            });
        }

        private List<Scope> scopesForAccount(long accountId) {
            return db.sql("SELECT product_id, trade_id, request_id FROM enforcement_scope_fixture WHERE run_id = ? AND account_id = ?")
                    .param(RUN_ID).param(accountId)
                    .query((row, index) -> new Scope(row.getLong("product_id"), row.getLong("trade_id"),
                            row.getLong("request_id"))).list();
        }

        private List<Scope> scopesForProduct(long productId) {
            return db.sql("SELECT product_id, trade_id, request_id FROM enforcement_scope_fixture WHERE run_id = ? AND product_id = ?")
                    .param(RUN_ID).param(productId)
                    .query((row, index) -> new Scope(row.getLong("product_id"), row.getLong("trade_id"),
                            row.getLong("request_id"))).list();
        }

        private void maybeFail(SubjectCommand command) {
            if (failures.remove(command.enforcementId())) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "subject state conflict");
            }
        }

        private String current(String subject, long id) {
            return db.sql("""
                    SELECT state FROM enforcement_subject_fixture WHERE run_id = ? AND subject = ? AND subject_id = ?
                    """).param(RUN_ID).param(subject).param(id).query(String.class).single();
        }

        private void write(String subject, long id, String state, long sourceRef) {
            db.sql("""
                    INSERT INTO enforcement_subject_fixture (run_id, subject, subject_id, state, source_ref)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (run_id, subject, subject_id)
                    DO UPDATE SET state = EXCLUDED.state, source_ref = EXCLUDED.source_ref,
                        updated_at = statement_timestamp()
                    """).param(RUN_ID).param(subject).param(id).param(state).param(Long.toString(sourceRef)).update();
        }

        private static long stableId(SubjectCommand command) {
            return 100_000L + Math.floorMod(command.enforcementId().hashCode(), 100_000);
        }
    }

    private record Scope(long productId, long tradeId, long requestId) {}

    @TestConfiguration(proxyBeanMethods = false)
    static class Fixtures {
        @Bean
        LockTrace lockTrace() {
            return new LockTrace();
        }

        @Bean
        FixtureSubjects fixtureSubjects(JdbcClient db, LockTrace trace) {
            return new FixtureSubjects(db, trace);
        }

        @Bean
        FixtureCases fixtureCases(JdbcClient db, LockTrace trace) {
            return new FixtureCases(db, trace);
        }

        @Bean
        EnforcementApplication enforcementApplication(WriteExecutor writes, FileReferences files, JsonMapper json,
                                                       FixtureSubjects subjects, FixtureCases cases) {
            return new EnforcementApplication(writes, cases, subjects, subjects, subjects, subjects,
                    (transaction, eventType, intentKey, source, recipients, reason, occurredAt) ->
                            transaction.addEventIntent(recipients, eventType.replace('.', '_'), 1,
                                    source, intentKey, null, null), files, json);
        }
    }
}
