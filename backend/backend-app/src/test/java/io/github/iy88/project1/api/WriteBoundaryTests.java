package io.github.iy88.project1.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.matchesPattern;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
    "spring.autoconfigure.exclude=org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration,"
            + "org.springframework.boot.data.redis.autoconfigure.DataRedisAutoConfiguration",
    "project1.http.allowed-origins=http://127.0.0.1:3000"
})
@AutoConfigureMockMvc
@Import(WriteBoundaryTests.TestBeans.class)
class WriteBoundaryTests {
    @Autowired
    private MockMvc mvc;

    @Test
    void rejectsMissingOriginAndInvalidToken() throws Exception {
        mvc.perform(post("/api/v1/test-write").header("X-CSRF-Token", "fixture"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));

        var response = mvc.perform(post("/api/v1/test-write").header("Origin", "http://127.0.0.1:3000")
                        .header("X-CSRF-Token", "wrong"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("CSRF_INVALID"))
                .andReturn().getResponse();
        assertThat(response.getContentAsString())
                .contains(response.getHeader("X-Request-Id"));
    }

    @Test
    void acceptsExactOriginAndUsesAServerGeneratedRequestId() throws Exception {
        mvc.perform(post("/api/v1/test-write").header("Origin", "http://127.0.0.1:3000")
                        .header("X-CSRF-Token", "fixture").header("X-Request-Id", "client-value")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"value\":1}"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-Id", matchesPattern("[a-f0-9-]{36}")));
        mvc.perform(post("/api/v1/test-write").header("Origin", "http://localhost:3000")
                        .header("X-CSRF-Token", "fixture"))
                .andExpect(status().isForbidden());
    }

    @Test
    void mapsInvalidJsonAndLeavesUnmappedRoutesToMvc() throws Exception {
        mvc.perform(post("/api/v1/test-write").header("Origin", "http://127.0.0.1:3000")
                        .header("X-CSRF-Token", "fixture").contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.error.code").value("INPUT_INVALID"));
        mvc.perform(post("/api/v1/unknown"))
                .andExpect(status().isNotFound());
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestBeans {
        @Bean
        public CsrfGuard.Verifier verifier() {
            return (request, token) -> "fixture".equals(token);
        }

        @Bean
        public TestController testController() {
            return new TestController();
        }
    }

    @RestController
    static class TestController {
        @PostMapping("/api/v1/test-write")
        public int write(@RequestBody Input input) {
            return input.value();
        }

        public record Input(int value) {}
    }
}
