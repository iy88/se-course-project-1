package io.github.iy88.project1.infrastructure;

import java.util.concurrent.TimeUnit;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Component;

import io.github.iy88.project1.messaging.TaskStream;

@Component
@Profile("delivery-worker & infrastructure & !dependency-probe")
public class DeliveryLoop {
    private final TaskStream tasks;

    public DeliveryLoop(TaskStream tasks) {
        this.tasks = tasks;
    }

    @Scheduled(fixedDelayString = "${WORK_SCAN_SECONDS:5}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void work() { tasks.consume(); }
}

@Configuration(proxyBeanMethods = false)
@Profile("(delivery-worker | delivery-scheduler) & infrastructure & !dependency-probe")
@EnableScheduling
class DeliveryScheduling {
    @Bean
    public ThreadPoolTaskScheduler deliveryScheduler() {
        var scheduler = new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(4);
        scheduler.setThreadNamePrefix("delivery-");
        scheduler.setWaitForTasksToCompleteOnShutdown(true);
        scheduler.setAwaitTerminationSeconds(20);
        return scheduler;
    }
}
