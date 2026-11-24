package io.github.iy88.project1.account.application;

/** Sends verification codes through the application's mail assembly. */
public interface VerificationMail {
    void sendCode(String recipient, String purpose, String code, long ttlSeconds);
}
