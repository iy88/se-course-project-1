package io.github.iy88.project1;

import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import org.springframework.core.env.Environment;

final class RequiredInfrastructureConfiguration {

    private static final List<String> SERVICE_KEYS = List.of(
            "DATABASE_URL", "DATABASE_USERNAME", "DATABASE_PASSWORD", "REDIS_URL", "REDIS_NAMESPACE");
    private static final List<String> PROBE_KEYS = List.of(
            "OSS_ENDPOINT", "OSS_REGION", "OSS_BUCKET", "OSS_PREFIX", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET",
            "SMTP_HOST", "SMTP_PORT", "SMTP_TLS_MODE", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM");

    private RequiredInfrastructureConfiguration() {
    }

    static void validate(Environment environment) {
        if (!environment.matchesProfiles("infrastructure", "dependency-probe")) {
            return;
        }
        var required = new ArrayList<>(SERVICE_KEYS);
        if (environment.matchesProfiles("dependency-probe")) {
            required.addAll(PROBE_KEYS);
        } else {
            required.addAll(List.of("HTTP_BIND_HOST", "HTTP_BIND_PORT"));
        }
        var missing = required.stream().filter(key -> isMissing(environment, key)).toList();
        if (!missing.isEmpty()) {
            throw new IllegalArgumentException("Missing configuration: " + String.join(", ", missing));
        }
        requireDatabaseName(environment.getRequiredProperty("DATABASE_URL"));
    }

    private static boolean isMissing(Environment environment, String key) {
        try {
            String value = environment.getProperty(key);
            return value == null || value.isBlank() || value.startsWith("${");
        } catch (IllegalArgumentException unresolvedPlaceholder) {
            return true;
        }
    }

    private static void requireDatabaseName(String value) {
        try {
            if (value.startsWith("jdbc:postgresql://")) {
                URI uri = URI.create(value.substring("jdbc:".length()));
                String path = uri.getRawPath();
                if (uri.getHost() != null && path != null && path.matches("/[A-Za-z_][A-Za-z0-9_]{0,62}")) {
                    return;
                }
            }
        } catch (IllegalArgumentException malformedUrl) {
            // Report the field name without printing the connection string.
        }
        throw new IllegalArgumentException("Invalid configuration: DATABASE_URL must include an explicit PostgreSQL database name");
    }
}
