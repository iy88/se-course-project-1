package io.github.iy88.project1;

import io.github.iy88.project1.bootstrap.BackendStartup;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class BackendAppApplication {

    public static void main(String[] args) {
        BackendStartup.run(BackendAppApplication.class, args);
    }
}
