package io.github.iy88.project1.infrastructure;

import java.util.concurrent.TimeUnit;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Component;

import io.github.iy88.project1.messaging.EventDispatch;
import io.github.iy88.project1.messaging.TaskStream;
import io.github.iy88.project1.messaging.UserEvents;

@Component
@Profile("delivery-worker & infrastructure & !dependency-probe")
public class DeliveryLoop {
    private final EventDispatch events;
    private final TaskStream tasks;
    private final UserEvents registry;

    public DeliveryLoop(EventDispatch events, TaskStream tasks, UserEvents registry) {
        this.events = events;
        this.tasks = tasks;
        this.registry = registry;
    }

    @Scheduled(fixedDelayString = "${WORK_SCAN_SECONDS:5}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void publish() { events.publishDue(); }

    @Scheduled(fixedDelayString = "${WORK_SCAN_SECONDS:5}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void work() { tasks.tick(); }

    @Scheduled(fixedDelayString = "${EVENT_CLEANUP_SCAN_SECONDS:300}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void prune() { registry.pruneExpired(); }
}

@Configuration(proxyBeanMethods = false)
@Profile("delivery-worker & infrastructure & !dependency-probe")
@EnableScheduling
class DeliveryScheduling {
    @Bean
    public ThreadPoolTaskScheduler deliveryScheduler() {
        var scheduler = new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(4);
        scheduler.setThreadNamePrefix("delivery-");
        return scheduler;
    }
}
