package io.github.iy88.project1;

import io.github.iy88.project1.core.HelloService;
import io.github.iy88.project1.infrastructure.SmtpProbeRecipient;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
public class BackendAppApplication {

    public static void main(String[] args) {
        var application = new SpringApplication(BackendAppApplication.class);
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

    @Bean
    HelloService helloService() {
        return new HelloService();
    }
}
