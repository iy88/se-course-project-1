package io.github.iy88.project1.product;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
@EnableConfigurationProperties(ProductSettings.class)
public class ProductConfiguration {
}
