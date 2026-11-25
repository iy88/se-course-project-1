package io.github.iy88.project1.api.trade;

import io.github.iy88.project1.account.application.AccountTradeService;
import io.github.iy88.project1.api.account.CurrentAccount;
import io.github.iy88.project1.product.application.ProductTradeStore;
import io.github.iy88.project1.trade.application.TradePorts;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/**
 * Production subject adapters for the trade module. The trade assembly declares these ports
 * required, so a missing adapter fails startup instead of silently disabling trade.
 */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
public class TradeSubjectConfiguration {
    @Bean
    TradePorts.Product tradeProductPort(ProductTradeStore products) {
        return new TradeProductAdapter(products);
    }

    @Bean
    TradePorts.Accounts tradeAccountsPort(AccountTradeService accounts) {
        return new TradeAccountsAdapter(accounts);
    }

    @Bean
    @ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
    TradeActorResolver tradeActorResolver(CurrentAccount accounts) {
        return new AccountTradeActorResolver(accounts);
    }
}
