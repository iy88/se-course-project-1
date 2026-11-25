package io.github.iy88.project1.casemanagement.persistence;

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

    public TradeTimeoutCases(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public long open(long tradeId, String reason, Instant at) {
        return jdbc.sql("""
                with created as (
                    insert into moderation_case (case_type, created_at)
                    values ('exception', :at)
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
    }

    public void lockAndValidate(long caseId, long managerId, long tradeId, String basisRef) {
        var facts = jdbc.sql("""
                select link.trade_id, c.claimed_manager_id,
                       exists (select 1 from moderation_case_action a
                               where a.case_id = c.id and a.action_kind = 'decide') as decided
                from moderation_case c join trade_timeout_case link on link.case_id = c.id
                where c.id = :caseId
                for update of c
                """)
                .param("caseId", caseId)
                .query((row, index) -> new CaseFacts(row.getLong("trade_id"),
                        row.getObject("claimed_manager_id", Long.class), row.getBoolean("decided")))
                .optional()
                .orElseThrow(TradeTimeoutCases::notVisible);
        if (facts.managerId() == null || facts.managerId() != managerId) {
            throw notVisible();
        }
        if (facts.tradeId() != tradeId) {
            throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项目标与交易不一致");
        }
        if (basisRef == null || basisRef.isBlank()) {
            throw new BusinessError("BASIS_REQUIRED", 422, "处置依据不能为空");
        }
        if (!facts.decided()) {
            throw new BusinessError("STATE_CONFLICT", 409, "事项尚未决定");
        }
    }

    private static BusinessError notVisible() {
        return new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
    }

    private record CaseFacts(long tradeId, Long managerId, boolean decided) {}
}
