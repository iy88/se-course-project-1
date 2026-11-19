package io.github.iy88.project1.maintenance;

import java.io.IOException;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

final class MaintenanceConfig {

    private final Properties properties = new Properties();

    MaintenanceConfig(Path path) throws IOException {
        try (var reader = Files.newBufferedReader(path)) {
            properties.load(reader);
        }
    }

    String required(String key) {
        String value = properties.getProperty(key);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Missing configuration: " + key);
        }
        return value;
    }

    String matching(String key, String pattern) {
        String value = required(key);
        if (!value.matches(pattern)) {
            throw new IllegalArgumentException("Invalid configuration: " + key);
        }
        return value;
    }

    PostgresUrl postgresUrl(String key) {
        String value = required(key);
        try {
            if (value.startsWith("jdbc:postgresql://")) {
                URI uri = URI.create(value.substring("jdbc:".length()));
                String path = uri.getRawPath();
                if (uri.getHost() != null && uri.getUserInfo() == null && uri.getFragment() == null
                        && path != null && path.matches("/[A-Za-z_][A-Za-z0-9_]{0,62}")) {
                    int port = uri.getPort() == -1 ? 5432 : uri.getPort();
                    if (port > 0 && port <= 65535) {
                        String query = uri.getRawQuery();
                        if (containsLogin(query)) {
                            throw new IllegalArgumentException();
                        }
                        String adminUrl = "jdbc:postgresql://" + uri.getRawAuthority() + "/postgres"
                                + (query == null ? "" : "?" + query);
                        return new PostgresUrl(value, uri.getHost().toLowerCase(java.util.Locale.ROOT),
                                port, path.substring(1), adminUrl);
                    }
                }
            }
        } catch (IllegalArgumentException ignored) {
            // JDBC URLs can contain credentials in query parameters.
        }
        throw new IllegalArgumentException("Invalid configuration: " + key
                + " (expected one PostgreSQL host and database, with credentials in separate fields)");
    }

    private static boolean containsLogin(String query) {
        if (query == null) {
            return false;
        }
        for (String parameter : query.split("&")) {
            String name = URLDecoder.decode(parameter.split("=", 2)[0], StandardCharsets.UTF_8);
            if ("user".equalsIgnoreCase(name) || "password".equalsIgnoreCase(name)) {
                return true;
            }
        }
        return false;
    }

    record PostgresUrl(String jdbcUrl, String host, int port, String database, String adminUrl) {
        String target() {
            return host + ":" + port + "/" + database;
        }
    }
}
