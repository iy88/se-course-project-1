package io.github.iy88.project1.storage;

import com.aliyun.sdk.service.oss2.credentials.Credentials;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import tools.jackson.databind.json.JsonMapper;

final class OssPostPolicy {
    private static final DateTimeFormatter SIGNING_DATE = DateTimeFormatter.ofPattern("uuuuMMdd", Locale.ROOT)
            .withZone(ZoneOffset.UTC);
    private static final DateTimeFormatter SIGNING_TIME = DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss'Z'", Locale.ROOT)
            .withZone(ZoneOffset.UTC);
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String V4_REQUEST = "aliyun_v4_request";
    private static final String SIGNATURE_VERSION = "OSS4-HMAC-SHA256";

    private OssPostPolicy() {}

    // The Java V2 SDK supplies credentials. Its PostObject sample defines the form signature derivation.
    static OssFileObjects.UploadForm sign(OssFileObjects.Location location, String region, Credentials credentials,
                                         Instant signedAt, Instant expiresAt, long sizeBytes, String contentType) {
        if (region == null || !region.matches("[a-z0-9]+(?:-[a-z0-9]+)*") || !credentials.hasKeys()) {
            throw new IllegalArgumentException("Invalid OSS signing region or credentials");
        }
        Duration ttl = Duration.between(signedAt, expiresAt);
        if (ttl.isZero() || ttl.isNegative() || ttl.compareTo(Duration.ofHours(1)) > 0 || sizeBytes <= 0
                || contentType == null || !contentType.matches("[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*")) {
            throw new IllegalArgumentException("Invalid OSS upload expiry, declared size or MIME type");
        }

        String date = SIGNING_DATE.format(signedAt);
        var fields = new LinkedHashMap<String, String>();
        fields.put("key", location.key());
        fields.put("x-oss-signature-version", SIGNATURE_VERSION);
        fields.put("x-oss-credential", credentials.accessKeyId() + "/" + date + "/" + region + "/oss/" + V4_REQUEST);
        fields.put("x-oss-date", SIGNING_TIME.format(signedAt));
        fields.put("x-oss-forbid-overwrite", "true");
        fields.put("x-oss-object-acl", "private");
        fields.put("x-oss-content-type", contentType);
        fields.put("success_action_status", "204");
        if (credentials.securityToken() != null && !credentials.securityToken().isBlank()) {
            fields.put("x-oss-security-token", credentials.securityToken());
        }

        var conditions = new ArrayList<Object>();
        conditions.add(Map.of("bucket", location.bucket()));
        fields.forEach((name, value) -> conditions.add(Map.of(name, value)));
        conditions.add(List.of("content-length-range", sizeBytes, sizeBytes));
        var policyData = new LinkedHashMap<String, Object>();
        policyData.put("expiration", expiresAt.toString());
        policyData.put("conditions", conditions);
        byte[] json = JSON.writeValueAsBytes(policyData);
        String policy = Base64.getEncoder().encodeToString(json);
        fields.put("policy", policy);
        fields.put("x-oss-signature", signature(credentials.accessKeySecret(), date, region, policy));

        var publicEndpoint = URI.create("https://" + location.bucket() + ".oss-" + region + ".aliyuncs.com/");
        return new OssFileObjects.UploadForm(publicEndpoint, Collections.unmodifiableMap(fields));
    }

    private static String signature(String secret, String date, String region, String policy) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            byte[] dateKey = sign(mac, ("aliyun_v4" + secret).getBytes(StandardCharsets.UTF_8), date);
            byte[] regionKey = sign(mac, dateKey, region);
            byte[] serviceKey = sign(mac, regionKey, "oss");
            byte[] signingKey = sign(mac, serviceKey, V4_REQUEST);
            return HexFormat.of().formatHex(sign(mac, signingKey, policy));
        } catch (GeneralSecurityException failure) {
            throw new IllegalStateException("Could not calculate OSS V4 signature", failure);
        }
    }

    private static byte[] sign(Mac mac, byte[] key, String value) throws GeneralSecurityException {
        mac.init(new SecretKeySpec(key, "HmacSHA256"));
        return mac.doFinal(value.getBytes(StandardCharsets.UTF_8));
    }
}
