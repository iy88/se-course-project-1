package io.github.iy88.project1.api.realtime;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("project1.realtime")
public record RealtimeSettings(int replayLimit, int headPollSeconds, int accountLimit, int sessionLimit,
                              int helloSeconds, int heartbeatSeconds, int idleSeconds, int maxFrameBytes,
                              int unacknowledged) {
    public RealtimeSettings {
        if (replayLimit < 1 || replayLimit > 1000 || headPollSeconds < 1 || headPollSeconds > 60
                || sessionLimit < 1 || accountLimit < sessionLimit || helloSeconds < 1 || helloSeconds > 15
                || heartbeatSeconds < 1 || idleSeconds <= heartbeatSeconds || idleSeconds > 3600
                || maxFrameBytes < 1024 || maxFrameBytes > 65536
                || unacknowledged < replayLimit || unacknowledged > 10000) {
            throw new IllegalArgumentException("Invalid realtime connection settings");
        }
    }
}
