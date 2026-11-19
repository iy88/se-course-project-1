package io.github.iy88.project1.infrastructure;

import io.github.iy88.project1.messaging.DeliverySettings;
import io.github.iy88.project1.storage.OssClients;
import io.github.iy88.project1.storage.OssFileObjects;
import io.github.iy88.project1.storage.persistence.FileCleanup;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@Profile("delivery-scheduler & file-cleanup & infrastructure & !dependency-probe")
public class FileCleanupLoop {
    private static final Logger LOG = LoggerFactory.getLogger(FileCleanupLoop.class);
    private final FileCleanup cleanup;
    private final int batchSize;
    private final ExternalProbeProperties.Oss oss;

    public FileCleanupLoop(FileCleanup cleanup, DeliverySettings settings, Environment environment) {
        this.cleanup = cleanup;
        batchSize = settings.batchSize();
        oss = new ExternalProbeProperties.Oss(environment.getRequiredProperty("OSS_ENDPOINT"),
                environment.getRequiredProperty("OSS_REGION"), environment.getRequiredProperty("OSS_BUCKET"),
                environment.getRequiredProperty("OSS_PREFIX"), environment.getRequiredProperty("OSS_ACCESS_KEY_ID"),
                environment.getRequiredProperty("OSS_ACCESS_KEY_SECRET"));
    }

    @Scheduled(fixedDelayString = "${FILE_CLEANUP_SCAN_SECONDS:300}", timeUnit = TimeUnit.SECONDS, scheduler = "deliveryScheduler")
    public void run() {
        var result = OssClients.use(oss.endpoint(), oss.region(), oss.accessKeyId(), oss.accessKeySecret(),
                client -> cleanup.runBatch(new OssFileObjects(client, oss.bucket(), oss.prefix()), batchSize));
        result.failures().forEach(failure -> LOG.warn("file_id={} result={} oss_request_id={}",
                failure.fileId(), failure.reason(), failure.requestId()));
    }
}
