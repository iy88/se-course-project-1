package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

@Service
@Profile("infrastructure")
public class EventReplay {
    private final UserEvents events;

    public EventReplay(UserEvents events) {
        this.events = events;
    }

    public UserEvents.Head head(ExecutionContext actor) {
        return events.head(account(actor));
    }

    public Page replay(ExecutionContext actor, UUID epoch, long after, int limit, Projector projector) {
        var page = events.scan(account(actor), epoch, after, limit);
        var frames = new ArrayList<Frame>();
        for (var event : page.events()) {
            boolean originatingRead = actor.originConnectionId() != null
                    && actor.originConnectionId().equals(event.originConnectionId())
                    && ("message_read".equals(event.type()) || "notification_read".equals(event.type()));
            var data = originatingRead ? Optional.<Map<String, ?>>empty() : projector.project(actor, event);
            if (data.isPresent()) {
                frames.add(new Hint(epoch, event.eventId(), event.sequence(), event.type(), event.schemaVersion(),
                        event.occurredAt(), Map.copyOf(data.get())));
            } else if (!frames.isEmpty() && frames.getLast() instanceof CursorAdvance range
                    && range.throughSequence() == event.sequence() - 1) {
                frames.set(frames.size() - 1, new CursorAdvance(epoch, range.fromSequence(), event.sequence()));
            } else {
                frames.add(new CursorAdvance(epoch, event.sequence(), event.sequence()));
            }
        }
        return new Page(List.copyOf(frames), page.nextSequence(), page.head().headSequence(), page.hasMore());
    }

    private static long account(ExecutionContext actor) {
        if (actor.actorKind() != ExecutionContext.ActorKind.ACCOUNT) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "请登录");
        }
        return Long.parseLong(actor.actorId());
    }

    @FunctionalInterface
    public interface Projector {
        /** Projects the source under the actor's current read permissions. */
        Optional<Map<String, ?>> project(ExecutionContext actor, UserEvents.Event event);
    }

    public sealed interface Frame permits Hint, CursorAdvance {}
    public record Hint(UUID epoch, UUID eventId, long accountSequence, String eventType, int schemaVersion,
                       Instant occurredAt, Map<String, ?> data) implements Frame {}
    public record CursorAdvance(UUID epoch, long fromSequence, long throughSequence) implements Frame {}
    public record Page(List<Frame> items, long nextSequence, long headSequence, boolean hasMore) {}
}
