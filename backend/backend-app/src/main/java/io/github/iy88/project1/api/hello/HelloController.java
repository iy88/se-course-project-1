package io.github.iy88.project1.api.hello;

import io.github.iy88.project1.application.hello.HelloService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class HelloController {

    private final HelloService helloService;

    @GetMapping("/api/v1/hello")
    public HelloResponse hello() {
        return new HelloResponse(helloService.greeting());
    }

    public record HelloResponse(String message) {
    }
}
