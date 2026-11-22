package io.github.iy88.project1.conversation;

import java.time.Clock;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(ConversationSettings.class)
public class ConversationConfiguration {
    @Bean
    Clock conversationClock() {
        return Clock.systemUTC();
    }
}
