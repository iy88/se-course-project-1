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

    @Test
    void acceptsManagerIdentityOptions() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "account", "create-manager", "--env-file", ".env.dev",
                "--email", "manager@example.invalid", "--display-name=测试管理员"
        });

        assertThat(options).isNotNull();
        assertThat(options.email()).isEqualTo("manager@example.invalid");
        assertThat(options.displayName()).isEqualTo("测试管理员");
    }

    @Test
    void rejectsIncompleteManagerIdentityAndPasswordArguments() {
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "account", "create-manager", "--env-file=.env.dev", "--email=manager@example.invalid"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "account", "create-manager", "--env-file=.env.dev", "--email=manager@example.invalid",
                "--display-name=管理员", "--password=unsupported"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "db", "migrate", "--env-file=.env.dev", "--email=manager@example.invalid"
        })).isNull();
    }

    @Test
    void parsesLoadSeedWithDefaultsAndExplicitResetAcknowledgement() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "seed", "load", "--env-file", ".env.dev", "--prepare-reset", "--tag", "baseline"
        });

        assertThat(options).isNotNull();
        assertThat(options.command()).isEqualTo("seed load");
        assertThat(options.users()).isEqualTo(100);
        assertThat(options.products()).isEqualTo(10000);
        assertThat(options.prepareReset()).isTrue();
        assertThat(options.tag()).isEqualTo("baseline");
        assertThat(options.manifest()).isNull();
    }

    @Test
    void parsesDemoSeedWithoutLeakingScaleKnobs() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "seed", "demo", "--env-file=.env.dev", "--prepare-reset",
                "--manifest", "var/demo/manifest.json", "--seed", "7"
        });

        assertThat(options).isNotNull();
        assertThat(options.command()).isEqualTo("seed demo");
        assertThat(options.manifest()).isEqualTo(Path.of("var/demo/manifest.json"));
        assertThat(options.seed()).isEqualTo(7);
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "seed", "demo", "--env-file=.env.dev", "--prepare-reset", "--users", "10"
        })).isNull();
    }

    @Test
    void parsesScopedOssResetAndRejectsEmptyPrefixes() {
        var options = MaintenanceCli.Options.parse(new String[]{
                "oss", "reset", "--env-file", ".env.dev", "--prefix", "project1/dev"
        });
        assertThat(options).isNotNull();
        assertThat(options.prefix()).isEqualTo("project1/dev");
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "oss", "reset", "--env-file", ".env.dev", "--prefix", ""
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "oss", "reset", "--env-file", ".env.dev", "--prefix", "project1/dev/"
        })).isNull();
    }

    @Test
    void seedParsingStillRequiresTheEnvironmentFileAndRejectsForeignOptions() {
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "seed", "load", "--prepare-reset"
        })).isNull();
        assertThat(MaintenanceCli.Options.parse(new String[]{
                "seed", "load", "--env-file", ".env.dev", "--prepare-reset", "--email", "x@example.test"
        })).isNull();
    }
}
