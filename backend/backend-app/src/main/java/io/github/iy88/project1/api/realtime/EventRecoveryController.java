package io.github.iy88.project1.api.realtime;

import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.messaging.EventReplay;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure & !dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@RequestMapping("/api/v1/account/events")
public class EventRecoveryController {
    private final EventReplay events;
    private final RealtimeAccess access;
    private final RealtimeSettings settings;

    public EventRecoveryController(EventReplay events, RealtimeAccess access, RealtimeSettings settings) {
        this.events = events;
        this.access = access;
        this.settings = settings;
    }

    @GetMapping("/head")
    public ResponseEntity<Map<String, Object>> head(HttpServletRequest request) {
        var session = access.authenticate(request);
        access.requireCurrent(session);
        return response(EventWire.head(events.head(session.context(ApiRequestContext.requestId(request), null))));
    }

    @GetMapping
    public ResponseEntity<Map<String, Object>> replay(HttpServletRequest request, @RequestParam UUID epoch,
                                                      @RequestParam("after_seq") long after,
                                                      @RequestParam(required = false) Integer limit) {
        var session = access.authenticate(request);
        access.requireCurrent(session);
        var page = events.replay(session.context(ApiRequestContext.requestId(request), null),
                epoch, after, limit == null ? settings.replayLimit() : limit, access);
        access.requireCurrent(session);
        return response(Map.of("items", page.items().stream().map(EventWire::frame).toList(),
                "next_cursor", Map.of("epoch", epoch, "after_seq", page.nextSequence()),
                "head_seq", page.headSequence(), "has_more", page.hasMore()));
    }

    private static ResponseEntity<Map<String, Object>> response(Map<String, Object> body) {
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }
}
