package io.github.iy88.project1.bootstrap;

import io.github.iy88.project1.infrastructure.SmtpProbeRecipient;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.SpringApplication;

public final class BackendStartup {

    private BackendStartup() {
    }

    public static void run(Class<?> applicationClass, String[] args) {
        var application = new SpringApplication(applicationClass);
        application.setAdditionalProfiles("infrastructure");
        var arguments = new DefaultApplicationArguments(args);
        application.addInitializers(context -> {
            var environment = context.getEnvironment();
            ApplicationEnvFile.load(environment, arguments);
            if (environment.matchesProfiles("dependency-probe")) {
                var recipient = SmtpProbeRecipient.from(arguments);
                context.getBeanFactory().registerSingleton("smtpProbeRecipient", recipient);
            }
            RequiredInfrastructureConfiguration.validate(environment);
        });
        var context = application.run(args);
        if (context.getEnvironment().matchesProfiles("dependency-probe")) {
            context.close();
        }
    }
}
