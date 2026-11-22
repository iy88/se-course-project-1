package io.github.iy88.project1.account.application;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.util.Base64;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

@Component
@Profile("infrastructure")
public class PasswordHasher {
    private static final String ALGORITHM = "PBKDF2WithHmacSHA256";
    private static final String PREFIX = "pbkdf2-sha256";
    private static final int ITERATIONS = 210_000;
    private static final int KEY_LENGTH = 32;
    private static final int SALT_LENGTH = 16;
    private static final SecureRandom RANDOM = new SecureRandom();

    public String hash(String password) {
        byte[] salt = new byte[SALT_LENGTH];
        RANDOM.nextBytes(salt);
        byte[] derived = derive(password.toCharArray(), salt, ITERATIONS, KEY_LENGTH);
        return PREFIX + "$" + ITERATIONS + "$" + base64(salt) + "$" + base64(derived);
    }

    public boolean matches(String password, String stored) {
        if (password == null || stored == null) {
            return false;
        }
        String[] parts = stored.split("\\$");
        if (parts.length != 4 || !PREFIX.equals(parts[0])) {
            return false;
        }
        int iterations;
        byte[] salt;
        byte[] expected;
        try {
            iterations = Integer.parseInt(parts[1]);
            if (iterations < 100_000 || iterations > 2_000_000) {
                return false;
            }
            salt = Base64.getUrlDecoder().decode(parts[2]);
            expected = Base64.getUrlDecoder().decode(parts[3]);
        } catch (IllegalArgumentException invalid) {
            return false;
        }
        byte[] actual = derive(password.toCharArray(), salt, iterations, expected.length);
        return MessageDigest.isEqual(expected, actual);
    }

    public boolean matchesDummy(String password) {
        return matches(password, "pbkdf2-sha256$210000$" + base64(new byte[SALT_LENGTH]) + "$"
                + base64(new byte[KEY_LENGTH]));
    }

    private static byte[] derive(char[] password, byte[] salt, int iterations, int length) {
        PBEKeySpec spec = new PBEKeySpec(password, salt, iterations, length * 8);
        try {
            return SecretKeyFactory.getInstance(ALGORITHM).generateSecret(spec).getEncoded();
        } catch (NoSuchAlgorithmException | InvalidKeySpecException impossible) {
            throw new IllegalStateException("PBKDF2 is unavailable", impossible);
        } finally {
            spec.clearPassword();
        }
    }

    private static String base64(byte[] value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
    }

    public static byte[] utf8(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
}
