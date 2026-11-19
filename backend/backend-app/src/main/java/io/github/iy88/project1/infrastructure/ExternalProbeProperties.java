package io.github.iy88.project1.infrastructure;

import jakarta.mail.internet.AddressException;
import jakarta.mail.internet.InternetAddress;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.Assert;

@ConfigurationProperties("project1.probe")
record ExternalProbeProperties(Oss oss, Smtp smtp) {

    public record Oss(String endpoint, String region, String bucket, String prefix,
                      String accessKeyId, String accessKeySecret) {

        public Oss {
            required(region, "OSS_REGION");
            Assert.isTrue(region.matches("[a-z0-9-]+"), "OSS_REGION must be an OSS region ID");
            String host = "https://oss-" + region;
            Assert.isTrue((host + ".aliyuncs.com").equals(endpoint)
                            || (host + "-internal.aliyuncs.com").equals(endpoint),
                    "OSS_ENDPOINT must be the HTTPS OSS endpoint for OSS_REGION");
            required(bucket, "OSS_BUCKET");
            Assert.isTrue(bucket.matches("[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"), "OSS_BUCKET is invalid");
            required(prefix, "OSS_PREFIX");
            Assert.isTrue(prefix.matches("[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*") && prefix.length() <= 128,
                    "OSS_PREFIX must be a relative object prefix without a trailing slash");
            required(accessKeyId, "OSS_ACCESS_KEY_ID");
            required(accessKeySecret, "OSS_ACCESS_KEY_SECRET");
        }
    }

    enum TlsMode {
        STARTTLS, SSL
    }

    record Smtp(String host, int port, TlsMode tlsMode, String username, String password,
                String from) {

        Smtp {
            required(host, "SMTP_HOST");
            Assert.isTrue(host.matches("[A-Za-z0-9.-]+"), "SMTP_HOST must be a hostname");
            Assert.isTrue(port > 0 && port <= 65535, "SMTP_PORT must be between 1 and 65535");
            Assert.notNull(tlsMode, "SMTP_TLS_MODE must be starttls or ssl");
            required(username, "SMTP_USERNAME");
            required(password, "SMTP_PASSWORD");
            validateEmail(from, "SMTP_FROM");
        }

        private static void validateEmail(String value, String key) {
            required(value, key);
            try {
                var address = new InternetAddress(value, true);
                address.validate();
                Assert.isTrue(!address.isGroup(), key + " must be one mailbox");
            } catch (AddressException exception) {
                throw new IllegalArgumentException(key + " must be one mailbox");
            }
        }
    }

    private static void required(String value, String key) {
        Assert.isTrue(value != null && !value.isBlank() && !value.startsWith("${"),
                key + " is required");
    }
}
