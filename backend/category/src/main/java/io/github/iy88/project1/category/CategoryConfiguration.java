package io.github.iy88.project1.category;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
@EnableConfigurationProperties(CategorySettings.class)
public class CategoryConfiguration {
}
