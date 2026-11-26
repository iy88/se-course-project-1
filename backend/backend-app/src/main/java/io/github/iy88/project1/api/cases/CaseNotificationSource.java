package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.CaseVocabulary;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import java.util.Optional;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/**
 * Projects case lifecycle notifications for their current recipient.
 *
 * <p>The notification module keeps the recipient and event facts; this adapter re-checks the case
 * visibility at read time with the case-owned store and thread capability. A reporter may read the
 * confirmed anonymous result; a related account may read the case only through its own thread or
 * appeal eligibility. Manager projections, other threads, inquiry bodies, evidence and stored
 * reason/basis text are never consulted here.</p>
 */
@Component
@Profile("infrastructure & !dependency-probe & !file-probe")
class CaseNotificationSource implements NotificationSourcePort {
    private static final Set<String> EVENTS = Set.of(
            CaseVocabulary.EVENT_INQUIRY_CREATED,
            CaseVocabulary.EVENT_DECIDED,
            CaseVocabulary.EVENT_APPEAL_RESOLVED,
            CaseVocabulary.EVENT_RESULT_PUBLISHED,
            CaseVocabulary.EVENT_TRADE_FROZEN,
            CaseVocabulary.EVENT_TRADE_UNFROZEN,
            CaseVocabulary.EVENT_TRADE_ADJUSTED,
            CaseVocabulary.EVENT_CONTENT_REMOVED,
            CaseVocabulary.EVENT_EVALUATION_REMOVED);

    private final CaseLifecycleStore cases;
    private final CasePorts.Threads threads;

    CaseNotificationSource(CaseLifecycleStore cases, CasePorts.Threads threads) {
        this.cases = cases;
        this.threads = threads;
    }

    @Override
    public Optional<NotificationSourceView> project(ExecutionContext context, NotificationFacts facts) {
        var source = facts.source();
        if (context.actorKind() != ExecutionContext.ActorKind.ACCOUNT
                || !context.actorId().equals(Long.toString(facts.recipientAccountId()))
                || source == null
                || !CaseVocabulary.SOURCE_CASE.equals(source.type())
                || !EVENTS.contains(facts.eventType())) {
            return Optional.empty();
        }
        var caseFacts = cases.find(source.id()).orElse(null);
        if (caseFacts == null || !caseFacts.lifecycle()) {
            return Optional.empty();
        }
        long accountId = facts.recipientAccountId();
        if (CaseVocabulary.EVENT_RESULT_PUBLISHED.equals(facts.eventType())) {
            return publishedResult(caseFacts, accountId, facts.includeBody());
        }
        if (threads.findConversation(caseFacts.caseId(), accountId).isEmpty()
                && cases.appealEligibility(caseFacts.caseId(), accountId).isEmpty()) {
            return Optional.empty();
        }
        var notice = notice(facts.eventType());
        return Optional.of(new NotificationSourceView(notice.summary(), caseRef(caseFacts), null,
                facts.includeBody() ? notice.body() : null));
    }

    /** The result notification is reporter-only and uses the already-confirmed anonymous fields. */
    private Optional<NotificationSourceView> publishedResult(CaseRecords.Facts caseFacts, long accountId,
                                                             boolean includeBody) {
        if (!caseFacts.reportedBy(accountId) || caseFacts.publicResultAt() == null) {
            return Optional.empty();
        }
        return Optional.of(new NotificationSourceView("结案结果已确认公开", caseRef(caseFacts), null,
                includeBody ? publicBody(caseFacts) : null));
    }

    /** Joins only the public conclusion fields; private decision reasons stay in the case detail. */
    private static String publicBody(CaseRecords.Facts caseFacts) {
        String summary = caseFacts.publicSummary();
        String reason = caseFacts.publicReason();
        if (summary == null || summary.isBlank()) {
            return reason;
        }
        if (reason == null || reason.isBlank()) {
            return summary;
        }
        return summary + "\n\n" + reason;
    }

    private static ResourceRef caseRef(CaseRecords.Facts caseFacts) {
        return new ResourceRef(CaseVocabulary.SOURCE_CASE, caseFacts.caseId());
    }

    /** Fixed short event copy; detailed wording stays in the case detail projection. */
    private static CaseNotice notice(String eventType) {
        return switch (eventType) {
            case CaseVocabulary.EVENT_INQUIRY_CREATED -> new CaseNotice("收到事项问询",
                    "管理员发起了事项问询。你可以前往事项详情查看问询范围并回复。");
            case CaseVocabulary.EVENT_APPEAL_RESOLVED -> new CaseNotice("申辩已有处理结果",
                    "你的申辩已有处理结果。你可以前往事项详情查看处理记录。");
            case CaseVocabulary.EVENT_TRADE_FROZEN -> new CaseNotice("事项处置：冻结",
                    "相关交易已进入冻结处置。你可以前往事项详情查看处理记录。");
            case CaseVocabulary.EVENT_TRADE_UNFROZEN -> new CaseNotice("事项处置：解除",
                    "相关冻结处置已解除。你可以前往事项详情查看处理记录。");
            case CaseVocabulary.EVENT_TRADE_ADJUSTED -> new CaseNotice("事项处置：调整",
                    "相关交易状态已按处置结果调整。你可以前往事项详情查看处理记录。");
            case CaseVocabulary.EVENT_CONTENT_REMOVED -> new CaseNotice("事项处置：内容移除",
                    "相关内容已按处置结果移除。你可以前往事项详情查看处理记录。");
            case CaseVocabulary.EVENT_EVALUATION_REMOVED -> new CaseNotice("事项处置：评价移除",
                    "相关评价已按处置结果移除。你可以前往事项详情查看处理记录。");
            default -> new CaseNotice("事项处置结果",
                    "事项已完成处置。你可以前往事项详情查看处理记录。");
        };
    }

    private record CaseNotice(String summary, String body) {
    }
}
