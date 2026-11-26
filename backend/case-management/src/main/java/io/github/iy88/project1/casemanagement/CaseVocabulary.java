package io.github.iy88.project1.casemanagement;

import java.util.List;

/** Named case facts shared by the lifecycle use cases, the store and the query projections. */
public final class CaseVocabulary {
    private CaseVocabulary() {
    }

    public static final String REPORT = "report";
    public static final String PRODUCT_REVIEW = "product_review";
    public static final String DISPUTE = "dispute";
    public static final String EXCEPTION = "exception";

    public static final String PENDING = "pending";
    public static final String CLAIMED = "claimed";
    public static final String DECIDED = "decided";

    public static final String NO_ACTION = "no_action";
    public static final String NOT_ACTIONABLE = "not_actionable";
    public static final String VIOLATION = "violation";

    public static final List<String> DECISION_KINDS = List.of(NO_ACTION, NOT_ACTIONABLE, VIOLATION);

    public static final String ACTION_SUBMIT = "submit";
    public static final String ACTION_SUPPLEMENT = "supplement";
    public static final String ACTION_CLAIM = "claim";
    public static final String ACTION_INQUIRE = "inquire";
    public static final String ACTION_STATEMENT = "statement";
    public static final String ACTION_APPEAL = "appeal";
    public static final String ACTION_MANAGER_REPLY = "manager_reply";
    public static final String ACTION_DECIDE = "decide";
    public static final String ACTION_CLOSE = "close";
    public static final String ACTION_EXECUTE = "execute";
    public static final String ACTION_LIFT = "lift";
    public static final String ACTION_PUBLISH_RESULT = "publish_result";

    public static final String ACTOR_ACCOUNT = "account";
    public static final String ACTOR_MANAGER = "manager";
    public static final String ACTOR_SYSTEM = "system";

    public static final String VIEWPOINT_REPORTER = "reporter";
    public static final String VIEWPOINT_RELATED = "related_account";
    public static final String VIEWPOINT_MANAGER = "manager";

    public static final String SUPPLEMENT_EVIDENCE = "supplement_evidence";
    public static final String RESPOND_INQUIRY = "respond_inquiry";
    public static final String SUBMIT_APPEAL = "submit_appeal";
    public static final String INQUIRE = "inquire";
    public static final String DECIDE = "decide";
    public static final String RESOLVE_APPEAL = "resolve_appeal";
    public static final String CLOSE = "close";
    public static final String PUBLISH_RESULT = "publish_result";

    public static final String RESOLUTION_UPHOLD = "uphold";
    public static final String RESOLUTION_REVOKE = "revoke";
    public static final String RESOLUTION_ADJUST = "adjust";

    public static final List<String> RESOLUTIONS = List.of(RESOLUTION_UPHOLD, RESOLUTION_REVOKE, RESOLUTION_ADJUST);

    public static final String KIND_INQUIRY = "inquiry";
    public static final String KIND_STATEMENT = "statement";
    public static final String KIND_APPEAL = "appeal";
    public static final String KIND_MANAGER_REPLY = "manager_reply";
    public static final String KIND_SYSTEM_NOTICE = "system_notice";

    public static final String EVENT_INQUIRY_CREATED = "case.inquiry_created";
    public static final String EVENT_DECIDED = "case.decided";
    public static final String EVENT_APPEAL_RESOLVED = "case.appeal_resolved";
    public static final String EVENT_RESULT_PUBLISHED = "case.result_published";
    public static final String EVENT_TRADE_FROZEN = "case.trade_frozen";
    public static final String EVENT_TRADE_UNFROZEN = "case.trade_unfrozen";
    public static final String EVENT_TRADE_ADJUSTED = "case.trade_adjusted";
    public static final String EVENT_CONTENT_REMOVED = "case.content_removed";
    public static final String EVENT_EVALUATION_REMOVED = "case.evaluation_removed";

    public static final String SOURCE_CASE = "case";
    public static final String SOURCE_MESSAGE = "message";
    public static final String EVIDENCE_PLATFORM_RECORD = "platform_record";
    public static final String EVIDENCE_SUBMITTER_ATTACHMENT = "submitter_attachment";
    public static final List<String> CONVERSATION_KINDS = List.of("chat", "trade", "case");

    public static boolean isLifecycle(String caseType) {
        return !PRODUCT_REVIEW.equals(caseType);
    }
}
