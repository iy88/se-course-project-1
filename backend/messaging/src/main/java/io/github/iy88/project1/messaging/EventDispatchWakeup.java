package io.github.iy88.project1.messaging;

import java.util.concurrent.ThreadPoolExecutor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.transaction.event.TransactionalEventListener;

@Configuration(proxyBeanMethods = false)
@Profile("infrastructure & !dependency-probe & !file-probe")
class EventDispatchWakeup {
    private static final Logger LOG = LoggerFactory.getLogger(EventDispatchWakeup.class);

    @Bean(defaultCandidate = false)
    ThreadPoolTaskExecutor eventDispatchExecutor() {
        var executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(1);
        executor.setMaxPoolSize(1);
        // A queued drain covers all commits already visible when it starts.
        executor.setQueueCapacity(1);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.DiscardPolicy());
        executor.setThreadNamePrefix("event-dispatch-");
        return executor;
    }

    @Bean
    CommitListener eventDispatchCommitListener(EventDispatch dispatch, DeliverySettings settings,
            @Qualifier("eventDispatchExecutor") ThreadPoolTaskExecutor executor) {
        return new CommitListener(dispatch, settings, executor);
    }

    record CommitListener(EventDispatch dispatch, DeliverySettings settings, ThreadPoolTaskExecutor executor) {
        @TransactionalEventListener
        public void afterCommit(UserEvents.OutboxUpdated updated) {
            executor.execute(this::drain);
        }

        private void drain() {
            try {
                while (dispatch.publishDue() == settings.batchSize() && !Thread.currentThread().isInterrupted()) {
                    // Continue until there are no more full batches.
                }
            } catch (RuntimeException failure) {
                LOG.warn("event dispatch wakeup failed; the scheduled scan will retry", failure);
            }
        }
    }
}
