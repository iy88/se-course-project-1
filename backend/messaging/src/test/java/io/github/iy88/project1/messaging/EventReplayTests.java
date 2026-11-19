package io.github.iy88.project1.messaging;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.ResourceRef;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class EventReplayTests {
    @Test
    void mergesHiddenAndOriginReadEventsWithoutExposingTheirSource() {
        var events = mock(UserEvents.class);
        var epoch = UUID.randomUUID();
        var connection = UUID.randomUUID();
        var actor = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ACCOUNT,
                "12", UUID.randomUUID(), connection, 1L, "test");
        var source = new ResourceRef("notification", 77);
        var hidden = new UserEvents.Event(UUID.randomUUID(), 1L, "source_changed", 1, source, null,
                null, null, Instant.EPOCH);
        var own = new UserEvents.Event(UUID.randomUUID(), 2L, "notification_read", 1, source, null,
                null, connection, Instant.EPOCH);
        var visible = new UserEvents.Event(UUID.randomUUID(), 3L, "notification_created", 1, source, null,
                null, null, Instant.EPOCH);
        var head = new UserEvents.Head(epoch, 3L, 0);
        when(events.scan(12L, epoch, 0L, 5)).thenReturn(new UserEvents.Page(head, List.of(hidden, own, visible), 3, false));

        var page = new EventReplay(events).replay(actor, epoch, 0L, 5, (context, event) -> {
            assertThat(event).isNotEqualTo(own);
            return event.equals(visible) ? Optional.of(Map.of("notification_id", "77")) : Optional.empty();
        });

        assertThat(page.items()).containsExactly(new EventReplay.CursorAdvance(epoch, 1L, 2L),
                new EventReplay.Hint(epoch, visible.eventId(), 3L, "notification_created", 1, Instant.EPOCH,
                        Map.of("notification_id", "77")));
        assertThat(page.nextSequence()).isEqualTo(3);
    }

    @Test
    void rejectsAnEntryActorBeforeReadingAnEventHead() {
        var events = mock(UserEvents.class);
        var actor = new ExecutionContext(UUID.randomUUID(), ExecutionContext.ActorKind.ENTRY,
                "entry-fixture", null, null, null, "test");

        assertThatThrownBy(() -> new EventReplay(events).head(actor))
                .isInstanceOf(BusinessError.class)
                .extracting(failure -> ((BusinessError) failure).code())
                .isEqualTo("AUTHENTICATION_REQUIRED");
        verifyNoInteractions(events);
    }
}
