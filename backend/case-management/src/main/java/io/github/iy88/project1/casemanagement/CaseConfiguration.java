package io.github.iy88.project1.casemanagement;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/** Registers the case lifecycle settings for normal process roles. */
@Configuration(proxyBeanMethods = false)
@Profile("infrastructure")
@EnableConfigurationProperties(CaseSettings.class)
public class CaseConfiguration {
}
