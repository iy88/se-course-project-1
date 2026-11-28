package io.github.iy88.project1.integration;

import static org.assertj.core.api.Assertions.assertThat;

import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.integration.HttpItSupport.Session;
import java.net.URI;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Base64;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import tools.jackson.databind.JsonNode;

/** Account, session and credential HTTP flows including their validation and denial branches. */
class AccountEdgeHttpIT {
    private static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    private static HttpItSupport http;

    @BeforeAll
    static void start() throws Exception {
        http = HttpItSupport.start("account-edge");
    }

    @AfterAll
    static void stop() {
        if (http != null) {
            http.close();
        }
    }

    @Test
    void registrationVerificationAndLoginRejectInvalidCredentials() throws Exception {
        var guest = entry();
        var email = "register-" + RUN + "@example.invalid";
        var request = guestWrite(guest, "POST", "/account/email-verifications", """
                {"purpose":"registration","email":"%s"}
                """.formatted(email), 202);
        var verificationId = request.at("/requests/0/verification_id").asString();
        var code = http.db.sql("select code from email_verification where id = ?")
                .param(Long.parseLong(verificationId)).query(String.class).single();
        var wrongCode = differentCode(code);

        guestWrite(guest, "POST", "/accounts", """
                {"email":"%s","display_name":"New","password":"short","verification_id":"%s","code":"%s"}
                """.formatted(email, verificationId, code), 422);
        guestWrite(guest, "POST", "/accounts", """
                {"email":"%s","display_name":"New","password":"%s","verification_id":"not-a-number","code":"%s"}
                """.formatted(email, HttpItSupport.PASSWORD, code), 422);
        guestWrite(guest, "POST", "/accounts", """
                {"email":"%s","display_name":"New","password":"%s","verification_id":"%s","code":"%s"}
                """.formatted(email, HttpItSupport.PASSWORD, verificationId, wrongCode), 422);
        var registered = guestWrite(guest, "POST", "/accounts", """
                {"email":"%s","display_name":"New","password":"%s","verification_id":"%s","code":"%s"}
                """.formatted(email, HttpItSupport.PASSWORD, verificationId, code), 201);
        assertThat(registered.path("email").asString()).isEqualTo(email);
        guestWrite(guest, "POST", "/accounts", """
                {"email":"%s","display_name":"New","password":"%s","verification_id":"%s","code":"%s"}
                """.formatted(email, HttpItSupport.PASSWORD, verificationId, code), 422);

        guestWrite(guest, "POST", "/account/session",
                "{\"email\":\"" + email + "\",\"password\":\"wrong-password\"}", 401);
        guestWrite(guest, "POST", "/account/session",
                "{\"email\":\"bad-email\",\"password\":\"" + HttpItSupport.PASSWORD + "\"}", 401);
        guestWrite(guest, "POST", "/account/session",
                "{\"email\":\"" + email + "\",\"password\":\"" + HttpItSupport.PASSWORD + "\"}", 200);

        var resetEmail = "reset-" + RUN + "@example.invalid";
        var resetRequest = guestWrite(guest, "POST", "/account/email-verifications", """
                {"purpose":"password_reset","email":"%s"}
                """.formatted(resetEmail), 202);
        var resetId = resetRequest.at("/requests/0/verification_id").asString();
        guestWrite(guest, "POST", "/account/password-resets", """
                {"verification_id":"%s","code":"000000","new_password":"%s"}
                """.formatted(resetId, HttpItSupport.PASSWORD), 422);
        guestWrite(guest, "POST", "/account/password-resets", """
                {"verification_id":"999999999","code":"000000","new_password":"%s"}
                """.formatted(HttpItSupport.PASSWORD), 422);
    }

    @Test
    void profilePasswordEmailAndSessionChangesRevokeOnlyTheCurrentCredential() throws Exception {
        var account = http.account("account-owner", "user");
        var email = account.email();
        var session = http.get(account, "/account/session", 200);
        assertThat(session.path("account").path("account_id").asString())
                .isEqualTo(Long.toString(http.accountId(account)));
        http.get("/account/session", 401);

        http.patch(account, "/account/profile", "{}", 422);
        http.patch(account, "/account/profile", "{\"display_name\":5}", 422);
        http.patch(account, "/account/profile", "{\"avatar_file_id\":0}", 422);
        http.patch(account, "/account/profile", "{\"avatar_file_id\":\"bad\"}", 422);
        var profile = http.patch(account, "/account/profile",
                "{\"display_name\":\"Owner " + RUN + "\"}", 200);
        assertThat(profile.path("display_name").asString()).isEqualTo("Owner " + RUN);
        var removed = http.patch(account, "/account/profile", "{\"avatar_file_id\":null}", 200);
        assertThat(removed.path("avatar_url").isNull()).isTrue();

        http.put(account, "/account/password",
                "{\"current_password\":\"wrong\",\"new_password\":\"" + HttpItSupport.PASSWORD + "\"}", 422);
        http.put(account, "/account/password",
                "{\"current_password\":\"" + HttpItSupport.PASSWORD + "\",\"new_password\":\"short\"}", 422);
        var changedPassword = "Changed" + RUN + "Password1!";
        http.put(account, "/account/password",
                "{\"current_password\":\"" + HttpItSupport.PASSWORD + "\",\"new_password\":\""
                        + changedPassword + "\"}", 204);
        http.get(account, "/account/session", 401);
        var reauthenticated = http.login(email, changedPassword);
        assertThat(http.get(reauthenticated, "/account/session", 200).path("account").path("write_restricted")
                .asBoolean()).isFalse();

        var newEmail = "changed-" + RUN + "@example.invalid";
        var verifications = http.post(reauthenticated, "/account/email-verifications", """
                {"purpose":"email_change","email":"%s"}
                """.formatted(newEmail), 202);
        var oldId = verifications.at("/requests/0/verification_id").asString();
        var newId = verifications.at("/requests/1/verification_id").asString();
        http.put(reauthenticated, "/account/email", """
                {"new_email":"%s","old_verification_id":"%s","old_code":"000000",
                 "new_verification_id":"%s","new_code":"000000"}
                """.formatted(newEmail, oldId, newId), 422);
        http.put(reauthenticated, "/account/email", """
                {"new_email":"%s","old_verification_id":"999999999","old_code":"000000",
                 "new_verification_id":"999999998","new_code":"000000"}
                """.formatted(newEmail), 422);

        http.delete(reauthenticated, "/account/session", 204);
        http.get(reauthenticated, "/account/session", 401);
        http.delete(reauthenticated, "/account/session", 204);
    }

    @Test
    void malformedStoredSessionsAreRejectedWithoutAffectingOtherSessions() throws Exception {
        var account = http.account("account-session-owner", "user");
        rawGet("/account/session", null, 401);
        rawGet("/account/session", "", 401);
        rawGet("/account/session", "not-base64", 401);
        rawGet("/account/session", Base64.getUrlEncoder().withoutPadding()
                .encodeToString(new byte[32]), 401);

        var first = http.login(account.email());
        var second = http.login(account.email());
        assertThat(http.get(first, "/account/session", 200).path("account").path("account_id").asString())
                .isEqualTo(Long.toString(http.accountId(account)));
        http.delete(first, "/account/session", 204);
        http.get(first, "/account/session", 401);
        http.get(second, "/account/session", 200);

        var redis = http.app.getBean(StringRedisTemplate.class);
        String key = redisKey(second.token());
        redis.delete(key);
        http.get(second, "/account/session", 401);

        String malformed = http.login(account.email()).token();
        redis.opsForValue().set(redisKey(malformed), "not-a-session");
        rawGet("/account/session", malformed, 401);
    }

    private Guest entry() throws Exception {
        var response = http.http.send(HttpRequest.newBuilder(
                        URI.create(http.baseUrl + "/account/entry-context"))
                .timeout(Duration.ofSeconds(10)).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(200);
        var cookie = response.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0];
        return new Guest(cookie, http.json.readTree(response.body()).path("csrf_token").asString());
    }

    private JsonNode guestWrite(Guest guest, String method, String path, String body, int status)
            throws Exception {
        var request = HttpRequest.newBuilder(URI.create(http.baseUrl + path))
                .timeout(Duration.ofSeconds(10))
                .header("Origin", HttpItSupport.ORIGIN)
                .header("Cookie", guest.cookie())
                .header("X-CSRF-Token", guest.csrf())
                .header("Idempotency-Key", http.key())
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body))
                .build();
        return http.send(request, status);
    }

    private JsonNode rawGet(String path, String cookieToken, int status) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create(http.baseUrl + path))
                .timeout(Duration.ofSeconds(10));
        if (cookieToken != null) {
            builder.header("Cookie", "__Host-se_session=" + cookieToken);
        }
        return http.send(builder.GET().build(), status);
    }

    private String redisKey(String token) {
        byte[] digest = SessionService.sha256(Base64.getUrlDecoder().decode(token));
        var hex = new StringBuilder(digest.length * 2);
        for (byte part : digest) {
            hex.append(Character.forDigit((part >> 4) & 0xF, 16))
                    .append(Character.forDigit(part & 0xF, 16));
        }
        String namespace = http.app.getEnvironment().getProperty("project1.redis.namespace");
        return namespace + ":session:" + hex;
    }

    private static String differentCode(String code) {
        return "000000".equals(code) ? "111111" : "000000";
    }

    private record Guest(String cookie, String csrf) {
    }
}
