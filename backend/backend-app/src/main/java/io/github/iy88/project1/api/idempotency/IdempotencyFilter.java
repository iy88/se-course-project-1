package io.github.iy88.project1.api.idempotency;

import io.github.iy88.project1.account.application.EntryTokenService;
import io.github.iy88.project1.account.application.SessionService;
import io.github.iy88.project1.api.ApiRequestContext;
import io.github.iy88.project1.api.account.AccountCookies;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.WriteSettings;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingResponseWrapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Component
@Profile("infrastructure")
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class IdempotencyFilter extends OncePerRequestFilter {
    private static final Set<String> SAFE = Set.of("GET", "HEAD", "OPTIONS", "TRACE");
    private static final Pattern REVIEW_WRITES = Pattern.compile(
            "/api/v1/admin/(cases/[^/]+/claim|product-reviews/[^/]+/decision)");
    private static final Pattern NOTIFICATION_READ = Pattern.compile("/api/v1/account/notifications/[^/]+/read");
    private static final String DIGEST_VERSION = "s2-v1";

    private final JdbcClient jdbc;
    private final TransactionTemplate transaction;
    private final SessionService sessions;
    private final EntryTokenService entries;
    private final WriteSettings settings;
    private final JsonMapper json;
    private final String configVersion;

    public IdempotencyFilter(JdbcClient jdbc, PlatformTransactionManager manager, SessionService sessions,
                             EntryTokenService entries, WriteSettings settings, JsonMapper json,
                             @Value("${project1.config-version}") String configVersion) {
        this.jdbc = jdbc;
        this.transaction = new TransactionTemplate(manager);
        this.sessions = sessions;
        this.entries = entries;
        this.settings = settings;
        this.json = json;
        this.configVersion = configVersion;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI().substring(request.getContextPath().length());
        String method = request.getMethod();
        // Review and notification commands authorize replays inside their own write transaction.
        return !path.startsWith("/api/v1/")
                || SAFE.contains(method)
                || ("POST".equals(method) && REVIEW_WRITES.matcher(path).matches())
                || ("PUT".equals(method) && NOTIFICATION_READ.matcher(path).matches());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        UUID requestId = ApiRequestContext.requestId(request);
        if (requestId == null) {
            requestId = UUID.randomUUID();
            response.setHeader("X-Request-Id", requestId.toString());
        }
        String key = request.getHeader("Idempotency-Key");
        Actor actor = actor(request);
        String operation = request.getMethod() + " " + request.getRequestURI();
        byte[] digest = null;
        Claim claim = null;
        byte[] requestBody = request.getInputStream().readAllBytes();
        HttpServletRequest wrappedRequest = new CachedBodyRequest(request, requestBody);
        if (key != null && actor != null) {
            if (key.isBlank() || key.length() > settings.idempotencyKeyMaxLength() || !key.matches("[!-~]+")) {
                writeError(response, 422, "INPUT_INVALID", "Idempotency-Key 无效", requestId);
                return;
            }
            digest = digest(request.getMethod(), request.getRequestURI(), requestBody);
            claim = claim(actor, operation, key, digest);
            if (claim.replay != null) {
                if (expiredUploadAuthorisation(request, claim.replay)) {
                    writeError(response, 409, "UPLOAD_AUTH_EXPIRED", "上传授权已过期", requestId);
                    return;
                }
                replay(response, claim.replay, requestId);
                return;
            }
            if (claim.conflict) {
                writeError(response, 409, "IDEMPOTENCY_PAYLOAD_CONFLICT", "幂等键对应其他请求", requestId);
                return;
            }
        }
        ContentCachingResponseWrapper wrappedResponse = new ContentCachingResponseWrapper(response);
        UUID operationId = claim == null ? UUID.randomUUID() : claim.operationId;
        try {
            chain.doFilter(wrappedRequest, wrappedResponse);
            int status = wrappedResponse.getStatus();
            byte[] body = wrappedResponse.getContentAsByteArray();
            if (claim != null && claim.operationId != null && claim.owner) {
                complete(claim.operationId, status, body);
            }
            if (status >= 200 && status < 300 && actor != null) {
                audit(requestId, operationId, actor, request, body);
            }
        } finally {
            wrappedResponse.copyBodyToResponse();
        }
    }

    private Claim claim(Actor actor, String operation, String key, byte[] digest) {
        UUID candidate = UUID.randomUUID();
        Instant expiresAt = Instant.now().plusSeconds(settings.idempotencyRetentionSeconds());
        int inserted;
        try {
            inserted = transaction.execute(status -> jdbc.sql("""
                            INSERT INTO operation_record (actor_kind, actor_id, operation_name, idempotency_key,
                                digest_version, request_digest, operation_id, expires_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT DO NOTHING
                            """)
                    .params(actor.kind, actor.id, operation, key, DIGEST_VERSION, digest, candidate,
                            java.sql.Timestamp.from(expiresAt))
                    .update());
        } catch (DataAccessException unavailable) {
            throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "服务暂不可用");
        }
        if (inserted == 1) {
            return new Claim(candidate, true, null, false);
        }
        var existing = jdbc.sql("""
                        SELECT operation_id, request_digest, response_status, response_data::text AS data
                        FROM operation_record
                        WHERE actor_kind = ? AND actor_id = ? AND operation_name = ? AND idempotency_key = ?
                        """)
                .params(actor.kind, actor.id, operation, key)
                .query((rs, row) -> new Stored(rs.getObject("operation_id", UUID.class),
                        rs.getBytes("request_digest"), rs.getObject("response_status", Integer.class),
                        rs.getString("data")))
                .optional()
                .orElseThrow(() -> new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "服务暂不可用"));
        if (!Arrays.equals(existing.digest(), digest)) {
            return new Claim(null, false, null, true);
        }
        if (existing.status() == null) {
            return new Claim(null, false, null, true);
        }
        return new Claim(existing.operationId(), false, new Replay(existing.status(), existing.data()), false);
    }

    private void complete(UUID operationId, int status, byte[] body) {
        try {
            if (status >= 200 && status < 300) {
                String data = body.length == 0 ? null : new String(body, StandardCharsets.UTF_8);
                transaction.executeWithoutResult(tx -> jdbc.sql("""
                                UPDATE operation_record SET response_status = ?, response_data = ?::jsonb
                                WHERE operation_id = ?
                                """)
                        .params(status, data, operationId).update());
            } else {
                transaction.executeWithoutResult(tx -> jdbc.sql(
                                "DELETE FROM operation_record WHERE operation_id = ?")
                        .param(operationId).update());
            }
        } catch (DataAccessException ignored) {
            // A failed bookkeeping write leaves a pending row; a retry receives a conflict instead of
            // executing the business action a second time.
        }
    }

    private void audit(UUID requestId, UUID operationId, Actor actor, HttpServletRequest request, byte[] body) {
        String action = action(request.getMethod(), request.getRequestURI());
        if (action == null) {
            return;
        }
        long resolved = targetId(body);
        if (resolved <= 0 && "ACCOUNT".equals(actor.kind)
                && (action.startsWith("account.") || action.startsWith("session."))) {
            try {
                resolved = Long.parseLong(actor.id);
            } catch (NumberFormatException ignored) {
                resolved = 0;
            }
        }
        if (resolved <= 0) {
            return;
        }
        long targetId = resolved;
        String targetType = action.substring(0, action.indexOf('.'));
        try {
            transaction.executeWithoutResult(tx -> jdbc.sql("""
                            INSERT INTO audit_record (request_id, operation_id, actor_kind, actor_id, action,
                                target_type, target_id, facts, config_version)
                            VALUES (?, ?, ?, ?, ?, ?, ?, '{}'::jsonb, ?)
                            """)
                    .params(requestId, operationId, actor.kind, actor.id, action, targetType, targetId,
                            configVersion)
                    .update());
        } catch (DataAccessException ignored) {
            // Audit bookkeeping must not turn a committed business result into an error response.
        }
    }

    private Actor actor(HttpServletRequest request) {
        String sessionCookie = AccountCookies.read(request, AccountCookies.SESSION);
        if (sessionCookie != null) {
            try {
                var identity = sessions.authenticate(sessionCookie);
                return new Actor("ACCOUNT", Long.toString(identity.account().id()));
            } catch (BusinessError ignored) {
                // Fall through to the account entry actor.
            }
        }
        String entryCookie = AccountCookies.read(request, AccountCookies.ENTRY);
        if (entryCookie != null) {
            try {
                var claims = entries.parse(entryCookie);
                return new Actor("ENTRY", hex(claims.nonceDigest()));
            } catch (BusinessError ignored) {
                return null;
            }
        }
        return null;
    }

    private byte[] digest(String method, String uri, byte[] body) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(method.getBytes(StandardCharsets.UTF_8));
            digest.update((byte) '\n');
            digest.update(uri.getBytes(StandardCharsets.UTF_8));
            digest.update((byte) '\n');
            digest.update(body);
            return digest.digest();
        } catch (Exception impossible) {
            throw new IllegalStateException("Could not digest the idempotent request", impossible);
        }
    }

    private boolean expiredUploadAuthorisation(HttpServletRequest request, Replay replay) {
        if (!request.getRequestURI().endsWith("/files/uploads") || replay.body() == null) {
            return false;
        }
        try {
            JsonNode node = json.readTree(replay.body());
            JsonNode expiresAt = node.get("expires_at");
            if (expiresAt == null || !expiresAt.isString()) {
                return false;
            }
            return !Instant.now().isBefore(Instant.parse(expiresAt.asString()));
        } catch (RuntimeException invalid) {
            return false;
        }
    }

    private void replay(HttpServletResponse response, Replay replay, UUID requestId) throws IOException {
        response.setStatus(replay.status());
        response.setHeader("X-Request-Id", requestId.toString());
        response.setHeader("X-Idempotent-Replay", "true");
        response.setHeader("Cache-Control", "no-store");
        if (replay.body() != null) {
            response.setContentType("application/json");
            response.getOutputStream().write(replay.body().getBytes(StandardCharsets.UTF_8));
        }
    }

    private void writeError(HttpServletResponse response, int status, String code, String message, UUID requestId)
            throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.setHeader("X-Request-Id", requestId.toString());
        response.setHeader("Cache-Control", "no-store");
        response.getOutputStream().write(("{\"error\":{\"code\":\"" + code + "\",\"message\":\"" + message
                + "\",\"details\":{}},\"request_id\":\"" + requestId + "\"}")
                .getBytes(StandardCharsets.UTF_8));
    }

    private long targetId(byte[] body) {
        if (body.length == 0) {
            return 0;
        }
        try {
            JsonNode root = json.readTree(new String(body, StandardCharsets.UTF_8));
            return findId(root);
        } catch (RuntimeException invalid) {
            return 0;
        }
    }

    private long findId(JsonNode node) {
        if (node == null) {
            return 0;
        }
        for (String name : List.of("id", "account_id", "product_id", "category_id", "application_id", "audit_id")) {
            JsonNode value = node.get(name);
            if (value != null && value.isString()) {
                try {
                    long id = Long.parseLong(value.asString());
                    if (id > 0) {
                        return id;
                    }
                } catch (NumberFormatException ignored) {
                    // Keep searching.
                }
            }
        }
        for (JsonNode child : node) {
            long id = findId(child);
            if (id > 0) {
                return id;
            }
        }
        return 0;
    }

    private static String action(String method, String path) {
        String upper = method.toUpperCase(Locale.ROOT);
        if (upper.equals("POST") && path.equals("/api/v1/accounts")) return "account.registered";
        if (upper.equals("POST") && path.equals("/api/v1/account/email-verifications"))
            return "account.verification_requested";
        if (upper.equals("POST") && path.equals("/api/v1/account/session")) return "session.issued";
        if (upper.equals("DELETE") && path.equals("/api/v1/account/session")) return "session.revoked";
        if (upper.equals("PUT") && path.equals("/api/v1/account/password")) return "account.password_changed";
        if (upper.equals("POST") && path.equals("/api/v1/account/password-resets")) return "account.password_reset";
        if (upper.equals("PUT") && path.equals("/api/v1/account/email")) return "account.email_changed";
        if (upper.equals("PATCH") && path.equals("/api/v1/account/profile")) return "account.profile_changed";
        if (upper.equals("POST") && path.equals("/api/v1/admin/categories")) return "category.created";
        if (upper.equals("PATCH") && path.matches("/api/v1/admin/categories/\\d+")) return "category.renamed";
        if (upper.equals("POST") && path.matches("/api/v1/admin/categories/\\d+/aliases"))
            return "category.alias_added";
        if (upper.equals("DELETE") && path.matches("/api/v1/admin/categories/\\d+/aliases/\\d+"))
            return "category.alias_removed";
        if (upper.equals("POST") && path.matches("/api/v1/admin/categories/\\d+/disable"))
            return "category.disabled";
        if (upper.equals("DELETE") && path.matches("/api/v1/admin/categories/\\d+")) return "category.deleted";
        if (upper.equals("PUT") && path.equals("/api/v1/admin/banned-items")) return "banned_scope.replaced";
        if (upper.equals("POST") && path.equals("/api/v1/admin/banned-items")) return "banned_item.created";
        if (upper.equals("PATCH") && path.matches("/api/v1/admin/banned-items/\\d+")) return "banned_item.updated";
        if (upper.equals("DELETE") && path.matches("/api/v1/admin/banned-items/\\d+")) return "banned_item.deleted";
        if (upper.equals("POST") && path.equals("/api/v1/products")) return "product.submitted";
        if (upper.equals("PATCH") && path.matches("/api/v1/products/\\d+")) return "product.edited";
        if (upper.equals("POST") && path.matches("/api/v1/products/\\d+/review-submissions"))
            return "product.review_resubmitted";
        if (upper.equals("POST") && path.matches("/api/v1/products/\\d+/withdrawal"))
            return "product.review_withdrawn";
        if (upper.equals("POST") && path.matches("/api/v1/products/\\d+/off-shelf")) return "product.off_shelf";
        if (upper.equals("POST") && path.matches("/api/v1/products/\\d+/on-shelf")) return "product.on_shelf";
        if (upper.equals("POST") && path.matches("/api/v1/products/\\d+/category-applications"))
            return "category_application.created";
        if (upper.equals("DELETE") && path.matches("/api/v1/products/\\d+/category-application"))
            return "category_application.withdrawn";
        return null;
    }

    private static String hex(byte[] value) {
        StringBuilder text = new StringBuilder(value.length * 2);
        for (byte part : value) {
            text.append(Character.forDigit((part >> 4) & 0xF, 16)).append(Character.forDigit(part & 0xF, 16));
        }
        return text.toString();
    }

    private static final class CachedBodyRequest extends HttpServletRequestWrapper {
        private final byte[] body;

        CachedBodyRequest(HttpServletRequest request, byte[] body) {
            super(request);
            this.body = body;
        }

        @Override
        public ServletInputStream getInputStream() {
            ByteArrayInputStream input = new ByteArrayInputStream(body);
            return new ServletInputStream() {
                @Override
                public int read() {
                    return input.read();
                }

                @Override
                public int read(byte[] buffer, int offset, int length) {
                    return input.read(buffer, offset, length);
                }

                @Override
                public boolean isFinished() {
                    return input.available() == 0;
                }

                @Override
                public boolean isReady() {
                    return true;
                }

                @Override
                public void setReadListener(ReadListener listener) {
                    throw new UnsupportedOperationException();
                }
            };
        }

        @Override
        public BufferedReader getReader() {
            Charset charset = getCharacterEncoding() == null ? StandardCharsets.UTF_8
                    : Charset.forName(getCharacterEncoding());
            return new BufferedReader(new InputStreamReader(getInputStream(), charset));
        }

        @Override
        public int getContentLength() {
            return body.length;
        }

        @Override
        public long getContentLengthLong() {
            return body.length;
        }
    }

    private record Actor(String kind, String id) {
    }

    private record Stored(UUID operationId, byte[] digest, Integer status, String data) {
    }

    private record Replay(int status, String body) {
    }

    private record Claim(UUID operationId, boolean owner, Replay replay, boolean conflict) {
    }
}
