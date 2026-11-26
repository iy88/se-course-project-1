package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.casemanagement.persistence.TradeTimeoutCases;
import io.github.iy88.project1.conversation.persistence.ConversationStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.application.TradePorts;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeCaseConfiguration {
    @Bean
    TradePorts.Cases tradeCases(TradeTimeoutCases cases, CaseLifecycleStore lifecycle,
                                ConversationStore conversations, Clock clock) {
        return new TradeCaseAdapter(cases, lifecycle, conversations, clock);
    }

    private record TradeCaseAdapter(TradeTimeoutCases cases, CaseLifecycleStore lifecycle,
                                    ConversationStore conversations, Clock clock) implements TradePorts.Cases {
        @Override
        public void lockAndValidate(WriteTransaction transaction, long caseId, long managerId, long tradeId,
                                    String basisRef) {
            var facts = lifecycle.requireLocked(transaction, caseId);
            if (!facts.claimedBy(managerId)) {
                throw new BusinessError("NOT_CASE_MANAGER", 404, "事项不可见");
            }
            if (facts.archived()) {
                throw new BusinessError("CASE_CLOSED", 409, "事项已结案");
            }
            if (!"trade".equals(facts.targetType()) || facts.targetId() == null || facts.targetId() != tradeId) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项目标与交易不一致");
            }
            if (basisRef == null || basisRef.isBlank()) {
                throw new BusinessError("BASIS_REQUIRED", 422, "处置依据不能为空");
            }
            if (!facts.decided()) {
                throw new BusinessError("STATE_CONFLICT", 409, "事项尚未决定");
            }
        }

        @Override
        public LockPlan prepareSelfResolution(long caseId) {
            var resources = new TreeSet<LockPlan.Key>();
            resources.add(CaseLifecycleStore.lockKey(caseId));
            for (long threadId : lifecycle.selfResolutionThreadIds(caseId)) {
                resources.add(new LockPlan.Key(LockPlan.Domain.CASE_CONVERSATION, List.of(threadId)));
            }
            return new LockPlan(Map.of(), resources);
        }

        @Override
        public void lockSelfResolution(WriteTransaction transaction, long caseId, long tradeId, long disputeId) {
            var facts = lifecycle.requireLocked(transaction, caseId);
            requireSelfResolutionCase(facts, tradeId);
            cases.requireDisputeLink(caseId, tradeId, disputeId);
        }

        @Override
        public void archiveSelfResolved(WriteTransaction transaction, long caseId, long tradeId, long disputeId,
                                        Instant at) {
            var facts = lifecycle.requireLocked(transaction, caseId);
            requireSelfResolutionCase(facts, tradeId);
            cases.requireDisputeLink(caseId, tradeId, disputeId);
            if (facts.archived()) {
                return;
            }
            for (long threadId : new TreeSet<>(lifecycle.selfResolutionThreadIds(caseId))) {
                var conversation = conversations.lockCase(transaction, threadId);
                conversations.archiveCase(transaction, conversation);
            }
            lifecycle.archiveSelfResolved(caseId, tradeId, disputeId, at);
        }

        private static void requireSelfResolutionCase(CaseRecords.Facts facts, long tradeId) {
            if (!"dispute".equals(facts.caseType())) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项类型不是交易争议");
            }
            if (!"trade".equals(facts.targetType()) || facts.targetId() == null || facts.targetId() != tradeId) {
                throw new BusinessError("TARGET_STATE_CONFLICT", 409, "事项目标与交易不一致");
            }
        }

        @Override
        public long openTimeoutCase(WriteTransaction transaction, ExecutionContext context, long tradeId,
                                    String reason) {
            return cases.open(tradeId, reason, clock.instant());
        }

        @Override
        public long openDisputeCase(WriteTransaction transaction, ExecutionContext context, long tradeId,
                                    long disputeId, java.time.Instant at) {
            return cases.openDispute(tradeId, disputeId, at);
        }
    }
}
