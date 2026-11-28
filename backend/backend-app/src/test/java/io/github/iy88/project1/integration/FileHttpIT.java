package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.net.InetSocketAddress;
import java.util.Base64;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/**
 * File metadata, target and completion rules through the public HTTP API. The local OSS endpoint is
 * intentionally unavailable, so the successful authorization path proves the signed form and
 * registration work while completion exercises the production storage-failure mapping.
 */
class FileHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static final byte[] PNG = Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=");
    private static HttpItSupport http;
    private static HttpServer objects;
    private static Session seller;
    private static Session other;

    @BeforeAll
    static void start() throws Exception {
        objects = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        objects.createContext("/", exchange -> {
            try {
                var headers = exchange.getResponseHeaders();
                headers.add("ETag", "\"fixture-etag\"");
                headers.add("Content-Type", "image/png");
                headers.add("Content-Length", Integer.toString(PNG.length));
                switch (exchange.getRequestMethod()) {
                    case "HEAD", "DELETE" -> exchange.sendResponseHeaders(
                            "DELETE".equals(exchange.getRequestMethod()) ? 204 : 200, -1);
                    default -> {
                        exchange.sendResponseHeaders(200, PNG.length);
                        exchange.getResponseBody().write(PNG);
                    }
                }
            } finally {
                exchange.close();
            }
        });
        objects.start();
        http = HttpItSupport.start("file-http",
                Map.of("OSS_ENDPOINT", "http://127.0.0.1:" + objects.getAddress().getPort()),
                new Class<?>[0]);
        seller = http.account("file-seller", "user");
        other = http.account("file-other", "user");
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
        if (objects != null) {
            objects.stop(0);
        }
    }

    @Test
    void uploadCapabilitiesMetadataTargetsAndCompletionUseBusinessRules() throws Exception {
        http.get("/files/upload-capabilities", 401);
        var capabilities = http.get(seller, "/files/upload-capabilities", 200);
        assertThat(capabilities.path("purposes").path("product_image").isObject()).isTrue();
        assertThat(capabilities.path("purposes").path("case_evidence").isObject()).isTrue();
        assertThat(capabilities.path("upload_ttl_seconds").asLong()).isPositive();

        http.writeWithoutKey(seller, "POST", "/files/uploads", """
                {"purpose":"product_image","declared_size":10,"declared_content_type":"image/png"}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"bad","declared_size":10,"declared_content_type":"image/png"}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":0,"declared_content_type":"image/png"}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":10}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":10,"declared_content_type":"text/plain"}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":999999999,"declared_content_type":"image/png"}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"account_avatar","declared_size":10,"declared_content_type":"image/png",
                 "target":{"resource_type":"product","resource_id":"1"}}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"case_evidence","declared_size":10,"declared_content_type":"image/png",
                 "target":{"resource_type":"product","resource_id":"1"}}
                """, 403);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":10,"declared_content_type":"image/png",
                 "target":{"resource_type":"account","resource_id":"1"}}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":10,"declared_content_type":"image/png",
                 "target":{"resource_type":"product","resource_id":"bad"}}
                """, 422);
        http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":10,"declared_content_type":"image/png",
                 "target":{"resource_type":"product","resource_id":"999999999"}}
                """, 404);

        long product = http.db.sql("""
                insert into product (seller_account_id, title, description, price_cents, lifecycle_state)
                values (?, ?, 'fixture', 100, 'pending_review') returning product_id
                """).param(http.accountId(seller)).param("File product " + RUN).query(Long.class).single();
        var authorized = http.post(seller, "/files/uploads", """
                {"purpose":"product_image","declared_size":%d,"declared_content_type":"image/png",
                 "target":{"resource_type":"product","resource_id":"%d"}}
                """.formatted(PNG.length, product), 201);
        String fileId = authorized.path("file_id").asString();
        assertThat(authorized.path("upload").path("url").asString()).startsWith("http");
        assertThat(authorized.path("upload").path("fields").isObject()).isTrue();
        assertThat(authorized.path("limits").path("max_bytes").asLong()).isPositive();

        var avatar = http.post(seller, "/files/uploads", """
                {"purpose":"account_avatar","declared_size":%d,"declared_content_type":"image/png"}
                """.formatted(PNG.length), 201);
        assertThat(avatar.path("file_id").asString()).isNotEqualTo(fileId);

        http.writeWithoutKey(seller, "POST", "/files/" + fileId + "/completion", null, 422);
        http.post(seller, "/files/not-a-number/completion", null, 422);
        http.post(seller, "/files/999999999/completion", null, 404);
        http.post(other, "/files/" + fileId + "/completion", null, 404);
        var completed = http.post(seller, "/files/" + fileId + "/completion", null, 200);
        assertThat(completed.path("file_id").asString()).isEqualTo(fileId);
        assertThat(completed.path("state").asString()).isEqualTo("verified");
        assertThat(completed.path("metadata").path("content_type").asString()).isEqualTo("image/png");
        assertThat(completed.path("metadata").path("size_bytes").asLong()).isEqualTo(PNG.length);
    }
}
