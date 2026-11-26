package io.github.iy88.project1.api.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationSourcePort.NotificationFacts;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.UUID;
import org.junit.jupiter.api.Test;

/** Content-removal notifications keep the recipient-only case projection and do not echo reasons. */
class CaseNotificationSourceTests {
    private static final long CASE = 41L;
    private static final long AUTHOR = 901L;
    private static final long OTHER = 902L;
    private static final Instant NOW = Instant.parse("2026-12-01T00:00:00Z");

    private final CaseLifecycleStore cases = mock(CaseLifecycleStore.class);
    private final CasePorts.Threads threads = mock(CasePorts.Threads.class);
    private final CaseNotificationSource source = new CaseNotificationSource(cases, threads);

    @Test
    void contentRemovalProjectsASafeAuthorNotice() {
        when(cases.find(CASE)).thenReturn(Optional.of(facts()));
        when(threads.findConversation(CASE, AUTHOR)).thenReturn(OptionalLong.of(71L));

        var view = source.project(context(AUTHOR), facts(CaseVocabulary.EVENT_CONTENT_REMOVED, AUTHOR,
                Map.of("reason", "举报人提供的私密说明")));

        assertThat(view).get().satisfies(notice -> {
            assertThat(notice.summary()).isEqualTo("事项处置：内容移除");
            assertThat(notice.body()).doesNotContain("举报人提供的私密说明");
            assertThat(notice.source()).isEqualTo(new ResourceRef("case", CASE));
            assertThat(notice.commentId()).isNull();
        });
    }

    @Test
    void evaluationRemovalUsesItsOwnSafeNotice() {
        when(cases.find(CASE)).thenReturn(Optional.of(facts()));
        when(threads.findConversation(CASE, AUTHOR)).thenReturn(OptionalLong.of(71L));

        var view = source.project(context(AUTHOR), facts(CaseVocabulary.EVENT_EVALUATION_REMOVED, AUTHOR, Map.of()));

        assertThat(view).get().satisfies(notice -> assertThat(notice.summary())
                .isEqualTo("事项处置：评价移除"));
    }

    @Test
    void anotherAccountCannotReadTheContentNotice() {
        when(cases.find(CASE)).thenReturn(Optional.of(facts()));

        assertThat(source.project(context(OTHER), facts(CaseVocabulary.EVENT_CONTENT_REMOVED, AUTHOR, Map.of())))
                .isEmpty();
    }

    private static NotificationFacts facts(String eventType, long recipient, Map<String, String> params) {
        return new NotificationFacts(1L, recipient, eventType, new ResourceRef("case", CASE), "case.decision",
                "1", params, NOW, null, "case:41:enf-1:removed", true);
    }

    private static CaseRecords.Facts facts() {
        return new CaseRecords.Facts(CASE, CaseVocabulary.REPORT, "comment", 501L, null, null, 902L,
                "请核实", 903L, NOW, CaseVocabulary.DECIDED, CaseVocabulary.VIOLATION, "认定违规", 903L,
                NOW, null, null, null, null, NOW, NOW);
    }

    private static ExecutionContext context(long account) {
        return new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                Long.toString(account), UUID.randomUUID(), null, 1L, "test");
    }
}
