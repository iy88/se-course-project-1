package io.github.iy88.project1.api;

import io.github.iy88.project1.core.HelloService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HelloController {

    private final HelloService helloService;

    public HelloController(HelloService helloService) {
        this.helloService = helloService;
    }

    @GetMapping("/api/v1/hello")
    public HelloResponse hello() {
        return new HelloResponse(helloService.greeting());
    }

    public record HelloResponse(String message) {
    }
}
