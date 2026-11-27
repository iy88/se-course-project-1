package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.casemanagement.application.ManagementCaseChange;
import io.github.iy88.project1.core.EventIntent;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.messaging.UserEvents;
import io.github.iy88.project1.notification.application.NotificationApplication;
import io.github.iy88.project1.notification.application.NotificationIntent;
import io.github.iy88.project1.notification.application.NotificationSourcePort;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@Component
@Profile("infrastructure & !dependency-probe & !file-probe")
class ManagementCaseNotifications implements NotificationSourcePort {
    private static final String EVENT_PREFIX = "management.case_";

    private final JdbcClient jdbc;
    private final NotificationApplication notifications;
    private final UserEvents events;

    ManagementCaseNotifications(JdbcClient jdbc, NotificationApplication notifications, UserEvents events) {
        this.jdbc = jdbc;
        this.notifications = notifications;
        this.events = events;
    }

    @TransactionalEventListener(phase = TransactionPhase.BEFORE_COMMIT)
    public void create(ManagementCaseChange change) {
        if ("inquire".equals(change.kind()) || "manager_reply".equals(change.kind())) return;
        var recipients = new HashSet<>(jdbc.sql("""
                select a.account_id
                from account a cross join moderation_case c
                where c.id = :caseId and a.role = 'manager'
                  and (:broadcast or c.claimed_manager_id is null or c.claimed_manager_id = a.account_id)
                """)
                .param("caseId", change.caseId())
                .param("broadcast", "opened".equals(change.kind()) || "claim".equals(change.kind()))
                .query(Long.class).list());
        if (Set.of("decide", "execute", "lift").contains(change.kind())) {
            recipients.remove(change.managerActorId());
        }
        if (recipients.isEmpty()) return;

        String type = EVENT_PREFIX + change.kind();
        String key = "management:case:" + change.caseId() + ":" + change.occurrence();
        var source = new ResourceRef("case", change.caseId());
        var params = new HashMap<String, String>();
        params.put("occurrence", change.occurrence());
        if (change.messageId() != null) params.put("message_id", change.messageId().toString());
        if (change.evidenceAnchorId() != null) params.put("evidence_id", change.evidenceAnchorId().toString());
        var intent = new NotificationIntent(recipients, null, type, source, key, type, "1", params,
                change.occurredAt());
        var pending = new ArrayList<EventIntent>();
        notifications.createNotifications((accounts, event, version, ref, intentKey, payload, sequence) ->
                accounts.stream().sorted().forEach(account -> pending.add(new EventIntent(
                        UUID.randomUUID(), account, event, version, ref, intentKey, payload, sequence))), intent);
        events.persist(new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.SYSTEM,
                "management-case-notifications", null, null, null, "1"), pending);
    }

    @Override
    public Optional<NotificationSourceView> project(ExecutionContext context, NotificationFacts facts) {
        if (!facts.eventType().startsWith(EVENT_PREFIX) || facts.source() == null
                || !"case".equals(facts.source().type()) || context.actorKind() != ExecutionContext.ActorKind.ACCOUNT
                || !context.actorId().equals(Long.toString(facts.recipientAccountId()))) {
            return Optional.empty();
        }

        return jdbc.sql("""
                select c.case_type, c.claimed_manager_id, (
                    select pa.audit_id from product_audit pa where pa.case_id = c.id
                ) as audit_id
                from moderation_case c
                join account a on a.account_id = :recipient and a.role = 'manager'
                where c.id = :caseId
                """)
                .param("recipient", facts.recipientAccountId())
                .param("caseId", facts.source().id())
                .query((row, index) -> {
                    boolean owns = Long.valueOf(facts.recipientAccountId())
                            .equals(row.getObject("claimed_manager_id", Long.class));
                    Long auditId = row.getObject("audit_id", Long.class);
                    boolean review = "product_review".equals(row.getString("case_type"));
                    ResourceRef destination = review
                            ? auditId != null && owns ? new ResourceRef("product_audit", auditId)
                                    : new ResourceRef("review_queue", facts.source().id())
                            : owns ? facts.source() : new ResourceRef("case_queue", facts.source().id());
                    String summary = summary(facts.eventType().substring(EVENT_PREFIX.length()));
                    String body = facts.includeBody()
                            ? "事项 #" + facts.source().id() + "。可通过管理端查看最新进度。"
                            : null;
                    String anchor = facts.includeBody() && owns && !review
                            ? anchor(facts.eventType(), facts.displayParams()) : null;
                    return new NotificationSourceView(summary, destination, "事项 #" + facts.source().id(), body,
                            null, null, anchor);
                }).optional();
    }

    private static String anchor(String eventType, Map<String, String> params) {
        String messageId = params.get("message_id");
        if (messageId != null && messageId.matches("[1-9][0-9]*")) {
            return "case-message-" + messageId;
        }
        String evidenceId = params.get("evidence_id");
        if (evidenceId != null && evidenceId.matches("[1-9][0-9]*")) {
            return "case-evidence-" + evidenceId;
        }
        String occurrence = params.get("occurrence");
        if (occurrence == null) return null;
        if (occurrence.matches("evidence:[1-9][0-9]*")) {
            return "case-evidence-" + occurrence.substring("evidence:".length());
        }
        if (occurrence.matches("action:[1-9][0-9]*")) {
            String prefix = (EVENT_PREFIX + "supplement").equals(eventType)
                    ? "case-supplement-" : "case-action-";
            return prefix + occurrence.substring("action:".length());
        }
        return null;
    }

    private static String summary(String kind) {
        return switch (kind) {
            case "opened" -> "有新的待处理事项";
            case "claim" -> "事项已认领";
            case "statement" -> "收到问询回复";
            case "appeal" -> "收到申辩";
            case "manager_reply" -> "申辩已有处理结果";
            case "supplement" -> "收到补充材料";
            case "evidence" -> "事项已添加证据";
            case "decide" -> "事项已作出决定";
            case "execute" -> "事项处置已执行";
            case "lift" -> "事项处置已解除";
            case "close" -> "事项已结案";
            case "publish_result" -> "事项结果已公开";
            case "classification_withdrawn" -> "待审核商品的分类申请已撤回";
            case "withdrawn" -> "商品审核已撤回";
            default -> "事项有新进展";
        };
    }
}
