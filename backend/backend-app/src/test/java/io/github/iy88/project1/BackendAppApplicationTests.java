package io.github.iy88.project1;

import io.github.iy88.project1.api.trade.TradeRequests;
import io.github.iy88.project1.trade.application.TradeApplication;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.ApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import tools.jackson.databind.json.JsonMapper;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "spring.autoconfigure.exclude="
        + "org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration,"
        + "org.springframework.boot.data.redis.autoconfigure.DataRedisAutoConfiguration")
@AutoConfigureMockMvc
class BackendAppApplicationTests {

    @Autowired
    private MockMvc mvc;

    @Autowired
    private JsonMapper json;

    @Autowired
    private ApplicationContext context;

    @Test
    void helloReturnsJsonForBrowserAcceptHeader() throws Exception {
        mvc.perform(get("/api/v1/hello")
                        .accept("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.message").value("Hello, Project1!"));
    }

    @Test
    void helloReturnsJsonWithoutAnAcceptHeader() throws Exception {
        mvc.perform(get("/api/v1/hello"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.message").value("Hello, Project1!"));
    }

    @Test
    void helloRejectsXmlOnlyRequests() throws Exception {
        mvc.perform(get("/api/v1/hello").accept(MediaType.APPLICATION_XML))
                .andExpect(status().isNotAcceptable());
    }

    @Test
    void tradeRequestJsonUsesSnakeCase() {
        var node = json.valueToTree(new TradeRequests.PurchaseRequest("note", 7));
        org.assertj.core.api.Assertions.assertThat(node.has("expected_product_version")).isTrue();
        var parsed = json.readValue("{\"expected_product_version\":7,\"note\":\"hello\"}",
                TradeRequests.PurchaseRequest.class);
        org.assertj.core.api.Assertions.assertThat(parsed.expectedProductVersion()).isEqualTo(7);
        org.assertj.core.api.Assertions.assertThat(parsed.note()).isEqualTo("hello");
    }

    @Test
    void tradeRoutesAreAbsentFromTheLightweightMvcSlice() throws Exception {
        org.assertj.core.api.Assertions.assertThat(context.getBeanNamesForType(TradeApplication.class)).isEmpty();
        mvc.perform(post("/api/v1/products/1/purchase-requests")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"expected_product_version\":1}"))
                .andExpect(status().isNotFound());
    }

    @Test
    void fileProbeRouteIsAbsentByDefault() throws Exception {
        mvc.perform(get("/__dev/file-probe/limits").header("X-File-Probe", "1"))
                .andExpect(status().isNotFound());
    }
}
