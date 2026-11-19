package io.github.iy88.project1.maintenance;

import java.nio.file.Path;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class MaintenanceCliTests {

    @Test
    void parsesTheRequiredEnvironmentFileAndAdministratorForInitialization() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "db", "init", "--env-file", ".env.dev", "--admin-user", "postgres"
        });

        assertThat(options).isNotNull();
        assertThat(options.envFile()).isEqualTo(Path.of(".env.dev"));
        assertThat(options.command()).isEqualTo("db init");
        assertThat(options.confirmation()).isNull();
        assertThat(options.adminUser()).isEqualTo("postgres");
    }

    @Test
    void acceptsInlineOptionValues() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "db", "reset", "--env-file=.env.prod", "--confirm=abc123"
        });

        assertThat(options).isNotNull();
        assertThat(options.envFile()).isEqualTo(Path.of(".env.prod"));
        assertThat(options.command()).isEqualTo("db reset");
        assertThat(options.confirmation()).isEqualTo("abc123");
        assertThat(options.adminUser()).isNull();
    }

    @Test
    void acceptsAdministratorResetOnlyAsALegacyFallback() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "db", "reset", "--env-file", ".env.prod", "--confirm", "abc123",
                "--admin-user", "postgres"
        });

        assertThat(options).isNotNull();
        assertThat(options.command()).isEqualTo("db reset");
        assertThat(options.confirmation()).isEqualTo("abc123");
        assertThat(options.adminUser()).isEqualTo("postgres");
    }

    @Test
    void requiresTheEnvironmentFileForEveryCommand() {
        assertThat(MaintenanceCli.Options.parse(new String[]{"db", "migrate"})).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{"db", "init", "--admin-user", "postgres"})).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{"db", "reset"})).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{"oss", "reset"})).isNull();
    }

    @Test
    void rejectsDuplicateAndUnknownOptions() {
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "db", "migrate", "--env-file", ".env.dev", "--env-file", ".env.prod"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "db", "migrate", "--env-file", ".env.dev", "--unknown", "value"
        })).isNull();
    }

    @Test
    void enforcesCommandSpecificOptions() {
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "db", "migrate", "--env-file", ".env.dev", "--confirm", "abc123"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "db", "init", "--env-file", ".env.dev", "--confirm", "abc123", "--admin-user", "postgres"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "db", "reset", "--env-file", ".env.dev", "--admin-user", "postgres"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "oss", "reset", "--env-file", ".env.dev", "--admin-user", "postgres"
        })).isNull();
    }
}
