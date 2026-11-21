package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.application.TradeApplication;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradeSettings;
import io.github.iy88.project1.trade.application.TradeTimeoutHandler;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.time.Clock;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import tools.jackson.databind.json.JsonMapper;

/**
 * Trade assembly for normal process roles. The infrastructure profile is present on API, worker and scheduler
 * entries; diagnostic probes and lightweight MVC slices do not assemble business dependencies. Missing ports fail
 * startup instead of disabling trade.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
@EnableConfigurationProperties(TradeSettings.class)
public class TradeConfiguration {
    @Bean
    public TradeApplication tradeApplication(TradeRepository repository, WriteExecutor writes, TaskSchedules schedules,
                                             TradeSettings settings, TradePorts.Product product,
                                             TradePorts.Accounts accounts, TradePorts.Conversation conversations,
                                             TradePorts.Cases cases, TradePorts.Notifications notifications,
                                             ObjectProvider<Clock> clocks, JsonMapper json) {
        return new TradeApplication(repository, writes, schedules, clocks.getIfAvailable(), settings,
                product, accounts, conversations, cases, notifications, json);
    }

    @Bean
    public TradeTimeoutHandler tradeTimeoutHandler(TradeApplication application) {
        return new TradeTimeoutHandler(application);
    }
}
