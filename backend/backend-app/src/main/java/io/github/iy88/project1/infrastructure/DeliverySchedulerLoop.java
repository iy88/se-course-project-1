package io.github.iy88.project1.infrastructure;

import io.github.iy88.project1.messaging.EventDispatch;
import io.github.iy88.project1.messaging.TaskStream;
import io.github.iy88.project1.messaging.UserEvents;
import java.util.concurrent.TimeUnit;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@Profile("delivery-scheduler & infrastructure & !dependency-probe")
public class DeliverySchedulerLoop {
    private final EventDispatch events;
    private final TaskStream tasks;
    private final UserEvents registry;

    public DeliverySchedulerLoop(EventDispatch events, TaskStream tasks, UserEvents registry) {
        this.events = events;
        this.tasks = tasks;
        this.registry = registry;
    }

    @Scheduled(fixedDelayString = "${WORK_SCAN_SECONDS:5}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void publish() { events.publishDue(); }

    @Scheduled(fixedDelayString = "${WORK_SCAN_SECONDS:5}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void enqueue() { tasks.enqueueDue(); }

    @Scheduled(fixedDelayString = "${EVENT_CLEANUP_SCAN_SECONDS:300}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void prune() { registry.pruneExpired(); }
}
