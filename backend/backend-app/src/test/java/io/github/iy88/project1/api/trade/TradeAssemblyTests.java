package io.github.iy88.project1.api.trade;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.messaging.TaskSchedules;
import io.github.iy88.project1.trade.application.TradeApplication;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.application.TradeTimeoutHandler;
import io.github.iy88.project1.trade.persistence.TradeRepository;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import tools.jackson.databind.json.JsonMapper;

class TradeAssemblyTests {
    private static final String[] SETTINGS = {
            "spring.profiles.active=infrastructure",
            "project1.trade.confirmation-wait-seconds=604800",
            "project1.trade.policy-version=s2-v1",
            "project1.trade.page-size-default=20",
            "project1.trade.page-size-max=100",
            "project1.trade.history-limit=200",
            "project1.write.lock-timeout-seconds=3",
            "project1.write.transaction-timeout-seconds=10",
            "project1.write.retry-limit=3",
            "project1.write.retry-base-milliseconds=50",
            "project1.write.idempotency-key-max-length=128",
            "project1.write.idempotency-retention-seconds=86400"
    };

    @Test
    void normalInfrastructureRoleAssemblesTradeWithoutAFeatureFlag() {
        runner().run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).hasSingleBean(TradeApplication.class);
            assertThat(context).hasSingleBean(TradeTimeoutHandler.class);
        });
    }

    @Test
    void missingPortFailsStartup() {
        runner(TradePorts.Cases.class).run(context -> {
            assertThat(context).hasFailed();
            assertThat(context.getStartupFailure()).hasRootCauseInstanceOf(
                    org.springframework.beans.factory.NoSuchBeanDefinitionException.class);
        });
    }

    private ApplicationContextRunner runner(Class<?>... omitted) {
        Set<Class<?>> without = Set.of(omitted);
        var runner = new ApplicationContextRunner()
                .withPropertyValues(SETTINGS)
                .withUserConfiguration(TradeConfiguration.class)
                .withBean(TradeRepository.class, () -> mock(TradeRepository.class))
                .withBean(WriteExecutor.class, () -> mock(WriteExecutor.class))
                .withBean(TaskSchedules.class, () -> mock(TaskSchedules.class))
                .withBean(JsonMapper.class, () -> JsonMapper.builder().build());
        if (!without.contains(TradePorts.Product.class)) {
            runner = runner.withBean(TradePorts.Product.class, () -> mock(TradePorts.Product.class));
        }
        if (!without.contains(TradePorts.Accounts.class)) {
            runner = runner.withBean(TradePorts.Accounts.class, () -> mock(TradePorts.Accounts.class));
        }
        if (!without.contains(TradePorts.Conversation.class)) {
            runner = runner.withBean(TradePorts.Conversation.class, () -> mock(TradePorts.Conversation.class));
        }
        if (!without.contains(TradePorts.Cases.class)) {
            runner = runner.withBean(TradePorts.Cases.class, () -> mock(TradePorts.Cases.class));
        }
        if (!without.contains(TradePorts.Notifications.class)) {
            runner = runner.withBean(TradePorts.Notifications.class,
                    () -> mock(TradePorts.Notifications.class));
        }
        return runner;
    }
}
