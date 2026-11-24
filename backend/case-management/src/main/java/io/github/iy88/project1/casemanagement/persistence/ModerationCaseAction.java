package io.github.iy88.project1.casemanagement.persistence;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "moderation_case_action")
class ModerationCaseAction {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "case_id", nullable = false)
    private long caseId;

    @Column(name = "action_kind", nullable = false)
    private String actionKind;

    @Column(name = "actor_account_id", nullable = false)
    private long actorAccountId;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    protected ModerationCaseAction() {
    }

    private ModerationCaseAction(long caseId, String actionKind, long actorAccountId, Instant occurredAt) {
        this.caseId = caseId;
        this.actionKind = actionKind;
        this.actorAccountId = actorAccountId;
        this.occurredAt = occurredAt;
    }

    static ModerationCaseAction claim(long caseId, long actorAccountId, Instant occurredAt) {
        return new ModerationCaseAction(caseId, "claim", actorAccountId, occurredAt);
    }

    static ModerationCaseAction decision(long caseId, long actorAccountId, Instant occurredAt) {
        return new ModerationCaseAction(caseId, "decide", actorAccountId, occurredAt);
    }
}
