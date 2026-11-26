package io.github.iy88.project1.casemanagement.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.casemanagement.CaseSettings;
import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.json.JsonMapper;

/** The case detail target snapshot is projected only to the current claimed manager. */
class CaseQueriesTests {
    private static final long CASE = 41L;
    private static final long REPORTER = 11L;
    private static final long AUTHOR = 21L;
    private static final long MANAGER = 31L;
    private static final long COMMENT = 501L;
    private static final Instant NOW = Instant.parse("2026-12-01T00:00:00Z");
    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final CaseLifecycleStore store = mock(CaseLifecycleStore.class);
    private final CasePorts.Threads threads = mock(CasePorts.Threads.class);
    private final CasePorts.Managers managers = mock(CasePorts.Managers.class);
    private final CasePorts.Targets targets = mock(CasePorts.Targets.class);
    private final CaseQueries queries = new CaseQueries(mock(JdbcClient.class), store, threads, managers,
            targets, new CaseSettings(), JSON, Clock.fixed(NOW, ZoneOffset.UTC));

    @Test
    void theClaimedManagerSeesTheExactContentSnapshot() {
        var facts = claimedFacts();
        when(store.find(CASE)).thenReturn(Optional.of(facts));
        when(threads.findConversation(CASE, MANAGER)).thenReturn(OptionalLong.empty());
        when(targets.contentTarget(facts)).thenReturn(Optional.of(new CasePorts.Targets.TargetSnapshot(
                "comment", COMMENT, AUTHOR, null, 99L, "被举报评论正文", "removed_by_admin", NOW, true)));

        when(targets.relatedAccountIds(facts)).thenReturn(Set.of(AUTHOR));
        when(targets.accountNames(Set.of(REPORTER, AUTHOR))).thenReturn(Map.of(AUTHOR, "评论作者"));

        var detail = queries.detail(context(MANAGER), CASE);

        assertThat(detail.path("related_accounts").get(0).path("reporter").asBoolean()).isTrue();
        assertThat(detail.path("related_accounts").get(0).path("eligible").asBoolean()).isFalse();
        assertThat(detail.path("related_accounts").get(1).path("display_name").asString()).isEqualTo("评论作者");
        assertThat(detail.path("related_accounts").get(1).path("eligible").asBoolean()).isTrue();
        assertThat(detail.path("target").path("context_id").asString()).isEqualTo("99");

        assertThat(detail.path("target").path("target_type").asString()).isEqualTo("comment");
        assertThat(detail.path("target").path("target_id").asString()).isEqualTo("501");
        assertThat(detail.path("target").path("author_account_id").asString()).isEqualTo("21");
        assertThat(detail.path("target").path("body").asString()).isEqualTo("被举报评论正文");
        assertThat(detail.path("target").path("removed").asBoolean()).isTrue();
    }

    @Test
    void aRelatedAccountDoesNotReceiveTheManagerSnapshot() {
        var facts = claimedFacts();
        when(store.find(CASE)).thenReturn(Optional.of(facts));
        when(threads.findConversation(CASE, AUTHOR)).thenReturn(OptionalLong.of(71L));

        var detail = queries.detail(context(AUTHOR), CASE);

        assertThat(detail.path("target").isMissingNode()).isTrue();
        assertThat(detail.path("reported_object").isMissingNode()).isTrue();
        assertThat(detail.path("related_accounts").isMissingNode()).isTrue();
    }

    private static CaseRecords.Facts claimedFacts() {
        return new CaseRecords.Facts(CASE, CaseVocabulary.REPORT, "comment", COMMENT, null, null, REPORTER,
                "请核实", MANAGER, NOW, CaseVocabulary.CLAIMED, null, null, null, null, null, null, null,
                null, NOW, NOW);
    }

    private static ExecutionContext context(long account) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(account), UUID.randomUUID(), null, 1L, "test");
    }
}
