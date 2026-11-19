package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.messaging.EventReplay;
import io.github.iy88.project1.messaging.UserEvents;
import java.util.Map;

final class EventWire {
    private EventWire() {}

    static Map<String, Object> head(UserEvents.Head head) {
        return Map.of("epoch", head.epoch(), "head_seq", head.headSequence(), "replay_floor", head.replayFloor());
    }

    static Map<String, Object> frame(EventReplay.Frame frame) {
        return switch (frame) {
            case EventReplay.Hint hint -> Map.of("type", "event", "epoch", hint.epoch(),
                    "event_id", hint.eventId(), "account_seq", hint.accountSequence(), "event_type", hint.eventType(),
                    "schema_version", hint.schemaVersion(), "occurred_at", hint.occurredAt(), "data", hint.data());
            case EventReplay.CursorAdvance advance -> Map.of("type", "cursor_advance", "epoch", advance.epoch(),
                    "from_seq", advance.fromSequence(), "through_seq", advance.throughSequence());
        };
    }
}
