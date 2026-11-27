package io.github.iy88.project1.casemanagement.persistence;

import io.github.iy88.project1.casemanagement.application.ManagementCaseChange;
import org.springframework.context.ApplicationEventPublisher;
import io.github.iy88.project1.core.BusinessError;
import java.time.Instant;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Repository
@Profile("infrastructure & !dependency-probe & !file-probe")
@Transactional(propagation = Propagation.MANDATORY)
public class TradeTimeoutCases {
    private final JdbcClient jdbc;
    private final ApplicationEventPublisher events;

    public TradeTimeoutCases(JdbcClient jdbc, ApplicationEventPublisher events) {
        this.jdbc = jdbc;
        this.events = events;
    }

    public long open(long tradeId, String reason, Instant at) {
        long caseId = jdbc.sql("""
                with created as (
                    insert into moderation_case (case_type, created_at, updated_at, target_type, target_id, case_status)
                    values ('exception', :at, :at, 'trade', :tradeId, 'pending')
                    returning id
                )
                insert into trade_timeout_case (case_id, trade_id, reason)
                select id, :tradeId, :reason from created
                returning case_id
                """)
                .param("at", java.sql.Timestamp.from(at))
                .param("tradeId", tradeId)
                .param("reason", reason)
                .query(Long.class)
                .single();
        events.publishEvent(ManagementCaseChange.opened(caseId, at));
        return caseId;
    }

    public long openDispute(long tradeId, long disputeId, Instant at) {
        long caseId = jdbc.sql("""
                with created as (
                    insert into moderation_case (case_type, created_at, updated_at, target_type, target_id, case_status)
                    values ('dispute', :at, :at, 'trade', :tradeId, 'pending')
                    returning id
                )
                insert into trade_dispute_case (case_id, dispute_id, trade_id)
                select id, :disputeId, :tradeId from created
                returning case_id
                """)
                .param("at", java.sql.Timestamp.from(at))
                .param("tradeId", tradeId)
                .param("disputeId", disputeId)
                .query(Long.class)
                .single();
        events.publishEvent(ManagementCaseChange.opened(caseId, at));
        return caseId;
    }

    public void lockAndValidate(long caseId, long managerId, long tradeId, String basisRef) {
        var facts = jdbc.sql("""
                select c.claimed_manager_id,
                       (select t.trade_id from trade_timeout_case t where t.case_id = c.id) as timeout_trade_id,
                       (select d.trade_id from trade_dispute_case d where d.case_id = c.id) as dispute_trade_id,
                       exists (select 1 from moderation_case_action a
                               where a.case_id = c.id and a.action_kind = 'decide') as decided
                from moderation_case c
                where c.id = :caseId
                for update of c
                """)
                .param("caseId", caseId)
                .query((row, index) -> new CaseFacts(row.getObject("timeout_trade_id", Long.class),
                        row.getObject("dispute_trade_id", Long.class),
                        row.getObject("claimed_manager_id", Long.class), row.getBoolean("decided")))
                .optional()
                .orElseThrow(TradeTimeoutCases::notVisible);
        Long linkedTrade = linkedTradeId(facts);
        if (linkedTrade == null) {
            throw notVisible();
        }
        if (facts.managerId() == null || facts.managerId() != managerId) {
            throw notVisible();
        }
        if (linkedTrade != tradeId) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项目标与交易不一致");
        }
        if (basisRef == null || basisRef.isBlank()) {
            throw new BusinessError("BASIS_REQUIRED", 422, "处置依据不能为空");
        }
        if (!facts.decided()) {
            throw new BusinessError("STATE_CONFLICT", 409, "事项尚未决定");
        }
    }

    /**
     * Verifies that the locked case, the dispute and the trade are linked by the same rows. The
     * caller owns the CASE row lock; this read never creates a missing historical case link.
     */
    public void requireDisputeLink(long caseId, long tradeId, long disputeId) {
        boolean linked = jdbc.sql("""
                select exists (
                    select 1
                      from trade_dispute_case d
                      join trade_dispute t on t.id = d.dispute_id
                     where d.case_id = :caseId
                       and d.dispute_id = :disputeId
                       and d.trade_id = :tradeId
                       and t.trade_id = :tradeId
                       and t.case_id = :caseId
                )
                """)
                .param("caseId", caseId)
                .param("disputeId", disputeId)
                .param("tradeId", tradeId)
                .query(Boolean.class)
                .single();
        if (!linked) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项与争议关联不一致");
        }
    }

    private static Long linkedTradeId(CaseFacts facts) {
        if (facts.timeoutTradeId() != null && facts.disputeTradeId() != null) {
            throw new BusinessError("STATE_CONFLICT", 409, "事项关联不唯一");
        }
        return facts.timeoutTradeId() != null ? facts.timeoutTradeId() : facts.disputeTradeId();
    }

    private static BusinessError notVisible() {
        return new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
    }

    private record CaseFacts(Long timeoutTradeId, Long disputeTradeId, Long managerId, boolean decided) {}
}
