package io.github.iy88.project1;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.util.Properties;
import org.springframework.boot.ApplicationArguments;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.core.env.StandardEnvironment;

final class ApplicationEnvFile {

    private ApplicationEnvFile() {
    }

    static void load(ConfigurableEnvironment environment, ApplicationArguments arguments) {
        var values = arguments.getOptionValues("env-file");
        if (values == null && !environment.matchesProfiles("infrastructure", "dependency-probe")) {
            return;
        }
        if (values == null || values.size() != 1 || values.getFirst().isBlank()) {
            throw new IllegalArgumentException("Provide exactly one --env-file=<path> for the application configuration");
        }

        Path path;
        try {
            path = Path.of(values.getFirst()).toAbsolutePath().normalize();
        } catch (InvalidPathException invalidPath) {
            throw new IllegalArgumentException("--env-file must be a valid file path");
        }
        if (!Files.isRegularFile(path)) {
            throw new IllegalArgumentException("--env-file is not a readable file: " + path);
        }

        var properties = new Properties();
        try (var reader = Files.newBufferedReader(path)) {
            properties.load(reader);
        } catch (IOException | IllegalArgumentException invalidFile) {
            throw new IllegalArgumentException("Could not read --env-file as Java properties: " + path);
        }

        environment.getPropertySources().addAfter(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME,
                new PropertiesPropertySource("applicationEnvFile", properties));
    }
}
