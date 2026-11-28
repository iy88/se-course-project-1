package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.BackendAppApplication;
import io.github.iy88.project1.account.application.AccountService;
import io.github.iy88.project1.account.application.PasswordHasher;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.account.AccountCookies;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.jdbc.core.simple.JdbcClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Shared HTTP fixture for integration suites that exercise the normal Spring entry points against
 * the isolated PostgreSQL/Redis instance prepared by the runner. Writes use the same session and
 * CSRF headers as a browser client; reads stay cookie-only.
 */
final class HttpItSupport implements AutoCloseable {
    static final String ORIGIN = "http://127.0.0.1:3000";
    static final String PASSWORD = "HttpIntegration2026!";

    final ConfigurableApplicationContext app;
    final JdbcClient db;
    final JsonMapper json;
    final HttpClient http;
    final String baseUrl;
    final String rootUrl;
    final String run;

    private final List<SessionService.Issued> sessions = new ArrayList<>();

    private HttpItSupport(ConfigurableApplicationContext app, String run) {
        this.app = app;
        this.db = app.getBean(JdbcClient.class);
        this.json = app.getBean(JsonMapper.class);
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        var port = ((ServletWebServerApplicationContext) app).getWebServer().getPort();
        this.rootUrl = "http://127.0.0.1:" + port;
        this.baseUrl = rootUrl + "/api/v1";
        this.run = run;
    }

    static HttpItSupport start(String suffix) throws IOException {
        return start(suffix, new Class<?>[0]);
    }

    static HttpItSupport start(String suffix, Class<?>... configurations) throws IOException {
        return startWithProfiles(suffix, "infrastructure", Map.of(), configurations);
    }

    static HttpItSupport start(String suffix, Map<String, String> overrides, Class<?>... configurations)
            throws IOException {
        return startWithProfiles(suffix, "infrastructure", overrides, configurations);
    }

    static HttpItSupport startWithProfiles(String suffix, String profiles, Class<?>... configurations)
            throws IOException {
        return startWithProfiles(suffix, profiles, Map.of(), configurations);
    }

    static HttpItSupport startWithProfiles(String suffix, String profiles, Map<String, String> overrides,
                                           Class<?>... configurations) throws IOException {
        var properties = new Properties();
        try (var reader = Files.newBufferedReader(Path.of(System.getProperty("it.envFile")))) {
            properties.load(reader);
        }
        if (!"dev".equals(properties.getProperty("APP_ENV"))) {
            throw new IllegalArgumentException("Integration requires APP_ENV=dev");
        }
        var namespace = properties.getProperty("REDIS_NAMESPACE");
        if (namespace == null || namespace.isBlank()) {
            throw new IllegalArgumentException("REDIS_NAMESPACE is required");
        }
        var run = suffix + "-" + UUID.randomUUID().toString().substring(0, 8);
        properties.setProperty("REDIS_NAMESPACE", namespace + ":" + run);
        properties.setProperty("ALLOWED_ORIGINS", ORIGIN);
        properties.setProperty("CONFIG_VERSION", run);
        overrides.forEach(properties::setProperty);
        properties.setProperty("DB_TRANSACTION_TIMEOUT_SECONDS", "30");
        properties.setProperty("DB_LOCK_TIMEOUT_SECONDS", "10");
        var primarySources = new Class<?>[configurations.length + 1];
        primarySources[0] = BackendAppApplication.class;
        System.arraycopy(configurations, 0, primarySources, 1, configurations.length);
        var application = new SpringApplication(primarySources);
        application.addInitializers(context -> context.getEnvironment().getPropertySources()
                .addFirst(new PropertiesPropertySource(run, properties)));
        var app = application.run("--spring.profiles.active=" + profiles, "--server.port=0",
                "--server.address=127.0.0.1", "--spring.main.banner-mode=off");
        return new HttpItSupport(app, run);
    }

    /** Creates one account row and signs in through the real service, returning a usable session. */
    Session account(String name, String role) {
        var email = name + "-" + run + "@example.invalid";
        var hash = app.getBean(PasswordHasher.class).hash(PASSWORD);
        db.sql("insert into account (email, display_name, password_hash, role) values (?, ?, ?, ?)")
                .param(email).param(name).param(hash).param(role).update();
        return login(email);
    }

    Session login(String email) {
        return login(email, PASSWORD);
    }

    Session login(String email, String password) {
        var issued = app.getBean(AccountService.class).login(email, password);
        sessions.add(issued);
        return new Session(issued, email, baseUrl);
    }

    void changePassword(String email, String password) {
        var account = db.sql("select account_id from account where email = ?")
                .param(email).query(Long.class).single();
        var hash = app.getBean(PasswordHasher.class).hash(password);
        db.sql("update account set password_hash = ?, credential_version = credential_version + 1 "
                        + "where account_id = ?")
                .param(hash).param(account).update();
    }

    JsonNode get(Session session, String path, int status) throws Exception {
        return send(session.request(path).GET().build(), status);
    }

    JsonNode get(String path, int status) throws Exception {
        return send(HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(10)).GET().build(), status);
    }

    JsonNode post(Session session, String path, String body, int status) throws Exception {
        return write(session, "POST", path, body, status);
    }

    JsonNode patch(Session session, String path, String body, int status) throws Exception {
        return write(session, "PATCH", path, body, status);
    }

    JsonNode put(Session session, String path, String body, int status) throws Exception {
        return write(session, "PUT", path, body, status);
    }

    JsonNode delete(Session session, String path, int status) throws Exception {
        return write(session, "DELETE", path, null, status);
    }

    JsonNode delete(Session session, String path, int status, String key) throws Exception {
        return write(session, "DELETE", path, null, status, key);
    }

    JsonNode write(Session session, String method, String path, String body, int status) throws Exception {
        var builder = session.request(path)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.issued.csrfToken())
                .header("Idempotency-Key", key())
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body));
        return send(builder.build(), status);
    }

    JsonNode writeWithoutKey(Session session, String method, String path, String body, int status)
            throws Exception {
        var builder = session.request(path)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.issued.csrfToken())
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body));
        return send(builder.build(), status);
    }

    JsonNode write(Session session, String method, String path, String body, int status, String key)
            throws Exception {
        var builder = session.request(path)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.issued.csrfToken())
                .header("Idempotency-Key", key)
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body));
        return send(builder.build(), status);
    }

    JsonNode send(HttpRequest request, int status) throws Exception {
        var response = http.send(request, HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).as("%s %s: %s", request.method(), request.uri().getPath(),
                response.body()).isEqualTo(status);
        if (response.body() == null || response.body().isBlank()) {
            return json.nullNode();
        }
        return json.readTree(response.body());
    }

    long accountId(Session session) {
        return session.issued.account().id();
    }

    String key() {
        return UUID.randomUUID().toString();
    }

    @Override
    public void close() {
        var contexts = app;
        try (contexts) {
            for (var session : sessions) {
                try {
                    app.getBean(SessionService.class).revoke(app.getBean(SessionService.class)
                            .authenticate(session.token()));
                } catch (RuntimeException ignored) {
                    // A test may already have changed the credential or revoked the session.
                }
            }
        }
    }

    record Session(SessionService.Issued issued, String email, String baseUrl) {
        HttpRequest.Builder request(String path) {
            return HttpRequest.newBuilder(URI.create(baseUrl + path))
                    .timeout(Duration.ofSeconds(10))
                    .header("Cookie", AccountCookies.SESSION + "=" + issued.token());
        }

        String token() {
            return issued.token();
        }

        String csrf() {
            return issued.csrfToken();
        }
    }
}
