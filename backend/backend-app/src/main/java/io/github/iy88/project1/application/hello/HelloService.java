package io.github.iy88.project1.application.hello;

import org.springframework.stereotype.Service;

@Service
public class HelloService {

    public String greeting() {
        return "Hello, Project1!";
    }
}
