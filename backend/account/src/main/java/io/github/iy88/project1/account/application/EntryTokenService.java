package io.github.iy88.project1.account.application;

import io.github.iy88.project1.account.AccountSettings;
import io.github.iy88.project1.core.BusinessError;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure")
public class EntryTokenService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();
    private final AccountSettings settings;
    private final byte[] key;

    public EntryTokenService(AccountSettings settings) {
        this.settings = settings;
        this.key = settings.entrySigningKey().getBytes(StandardCharsets.UTF_8);
    }

    public Issued issue() {
        Instant now = Instant.now();
        Instant expiresAt = now.plusSeconds(settings.entryTtlSeconds());
        String nonce = UUID.randomUUID().toString();
        byte[] csrf = new byte[32];
        RANDOM.nextBytes(csrf);
        byte[] csrfDigest = sha256(ENCODER.encodeToString(csrf));
        byte[] nonceDigest = sha256(nonce);
        String payload = settings.entryKeyVersion() + "|" + nonce + "|" + expiresAt.getEpochSecond() + "|"
                + ENCODER.encodeToString(csrfDigest);
        String cookie = ENCODER.encodeToString(payload.getBytes(StandardCharsets.UTF_8)) + "."
                + ENCODER.encodeToString(sign(payload));
        return new Issued(cookie, ENCODER.encodeToString(csrf), expiresAt, nonceDigest);
    }

    public Claims parse(String cookie) {
        if (cookie == null || cookie.isBlank()) {
            throw new BusinessError("AUTHENTICATION_REQUIRED", 401, "账户入口已失效");
        }
        String[] parts = cookie.split("\\.");
        if (parts.length != 2) {
            throw invalid();
        }
        String payload;
        byte[] signature;
        try {
            payload = new String(DECODER.decode(parts[0]), StandardCharsets.UTF_8);
            signature = DECODER.decode(parts[1]);
        } catch (IllegalArgumentException invalid) {
            throw invalid();
        }
        if (!MessageDigest.isEqual(sign(payload), signature)) {
            throw invalid();
        }
        String[] fields = payload.split("\\|", -1);
        if (fields.length != 4 || !settings.entryKeyVersion().equals(fields[0])) {
            throw invalid();
        }
        Instant expiresAt;
        byte[] csrfDigest;
        try {
            expiresAt = Instant.ofEpochSecond(Long.parseLong(fields[2]));
            csrfDigest = DECODER.decode(fields[3]);
        } catch (RuntimeException invalid) {
            throw invalid();
        }
        if (!Instant.now().isBefore(expiresAt)) {
            throw invalid();
        }
        return new Claims(sha256(fields[1]), csrfDigest, expiresAt);
    }

    public boolean csrfMatches(Claims claims, String token) {
        return token != null && MessageDigest.isEqual(claims.csrfDigest(), sha256(token));
    }

    private byte[] sign(String payload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(payload.getBytes(StandardCharsets.UTF_8));
        } catch (Exception impossible) {
            throw new IllegalStateException("HMAC is unavailable", impossible);
        }
    }

    public static byte[] sha256(String value) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static BusinessError invalid() {
        return new BusinessError("AUTHENTICATION_REQUIRED", 401, "账户入口已失效");
    }

    public record Issued(String cookie, String csrfToken, Instant expiresAt, byte[] nonceDigest) {
    }

    public record Claims(byte[] nonceDigest, byte[] csrfDigest, Instant expiresAt) {
    }
}
