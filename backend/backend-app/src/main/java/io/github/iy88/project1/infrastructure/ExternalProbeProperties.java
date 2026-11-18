package io.github.iy88.project1.infrastructure;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.Assert;

@ConfigurationProperties("project1.probe")
record ExternalProbeProperties(Oss oss) {

    record Oss(String endpoint, String region, String bucket, String prefix,
               String accessKeyId, String accessKeySecret) {

        Oss {
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

    private static void required(String value, String key) {
        Assert.isTrue(value != null && !value.isBlank() && !value.startsWith("${"),
                key + " is required");
    }
}
