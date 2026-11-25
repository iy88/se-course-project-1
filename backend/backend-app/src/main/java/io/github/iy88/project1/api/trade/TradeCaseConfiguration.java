package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.casemanagement.persistence.TradeTimeoutCases;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.application.TradePorts;
import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class TradeCaseConfiguration {
    @Bean
    TradePorts.Cases tradeCases(TradeTimeoutCases cases, Clock clock) {
        return new TimeoutCaseAdapter(cases, clock);
    }

    private record TimeoutCaseAdapter(TradeTimeoutCases cases, Clock clock) implements TradePorts.Cases {
        @Override
        public void lockAndValidate(WriteTransaction transaction, long caseId, long managerId, long tradeId,
                                    String basisRef) {
            cases.lockAndValidate(caseId, managerId, tradeId, basisRef);
        }

        @Override
        public long openTimeoutCase(WriteTransaction transaction, ExecutionContext context, long tradeId,
                                    String reason) {
            return cases.open(tradeId, reason, clock.instant());
        }
    }
}
