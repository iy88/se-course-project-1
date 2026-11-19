package io.github.iy88.project1;

import io.github.iy88.project1.core.HelloService;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
public class BackendAppApplication {

    public static void main(String[] args) {
        var application = new SpringApplication(BackendAppApplication.class);
        application.addInitializers(context -> RequiredInfrastructureConfiguration.validate(context.getEnvironment()));
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
