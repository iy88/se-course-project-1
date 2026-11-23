package io.github.iy88.project1.api.realtime;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("infrastructure & !dependency-probe & !file-probe")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@RequestMapping("/api/v1/capabilities")
public class CapabilitiesController {
    private final RealtimeSessions sessions;
    private final String configVersion;

    public CapabilitiesController(RealtimeSessions sessions,
                                  @Value("${project1.config-version}") String configVersion) {
        if (configVersion.isBlank()) throw new IllegalArgumentException("CONFIG_VERSION is required");
        this.sessions = sessions;
        this.configVersion = configVersion;
    }

    @GetMapping
    public ResponseEntity<Map<String, Object>> get(HttpServletRequest request) {
        sessions.resolve(request).ifPresent(sessions::requireCurrent);
        var limits = sessions.publicLimits();
        var body = Map.of(
                "config_version", configVersion,
                "limits", Map.of(
                        "password_min_length", limits.passwordMinLength(),
                        "password_max_length", limits.passwordMaxLength(),
                        "display_name_max_length", limits.displayNameMaxLength()));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }
}
