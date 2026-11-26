package io.github.iy88.project1.product.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Product-owned display restrictions.
 *
 * <p>A restriction is independent from the lifecycle and from occupancy: it only removes the
 * product from public detail, search and public interactions. Callers that change restrictions hold
 * the product row through their write transaction; this service never starts a transaction, sets
 * lifecycle state, changes occupancy or registers notifications.</p>
 */
@Service
@Profile("infrastructure")
public class ProductDisplayRestrictions {
    public static final String ADMIN_CASE = "admin_case";
    public static final String ACCOUNT_BAN = "account_ban";
    private static final Set<String> SOURCE_TYPES = Set.of(ADMIN_CASE, ACCOUNT_BAN);
    private static final String COLUMNS = """
            restriction_id, product_id, source_type, source_ref_id, reason, basis_ref,
            created_by, created_at, released_at, released_by, release_reason, release_basis_ref
            """;

    private final JdbcClient jdbc;

    public ProductDisplayRestrictions(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * Applies one source restriction. The caller must already hold the product {@code PRODUCT} lock
     * in its write transaction. Replaying the same active source returns the existing row.
     */
    public ApplyResult applyLocked(WriteTransaction transaction, long productId, String sourceType,
                                   long sourceRef, String reason, String basisRef, Instant occurredAt) {
        requireProductLock(transaction, productId);
        String type = sourceType(sourceType);
        long ref = positive(sourceRef, "来源标识");
        String text = required(reason, "限制原因");
        String basis = required(basisRef, "限制依据");
        Instant at = required(occurredAt);
        if (!productExists(productId)) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在");
        }
        long actor = actor(transaction);
        Optional<Long> existing = activeId(productId, type, ref);
        if (existing.isPresent()) {
            return new ApplyResult(existing.get(), type, ref, true);
        }
        long restrictionId = jdbc.sql("""
                        insert into product_display_restriction
                            (product_id, source_type, source_ref_id, reason, basis_ref, created_by, created_at)
                        values (?, ?, ?, ?, ?, ?, ?)
                        returning restriction_id
                        """)
                .param(productId).param(type).param(ref).param(text).param(basis).param(actor).param(time(at))
                .query(Long.class).single();
        return new ApplyResult(restrictionId, type, ref, false);
    }

    /**
     * Releases one restriction by identifier. The caller must already hold the product lock. A
     * repeated release returns the original result without writing again.
     */
    public ReleaseResult releaseLocked(WriteTransaction transaction, long productId, long restrictionId,
                                       String releaseReason, String releaseBasisRef, Instant occurredAt) {
        requireProductLock(transaction, productId);
        long id = positive(restrictionId, "限制标识");
        String reason = required(releaseReason, "解除原因");
        String basis = required(releaseBasisRef, "解除依据");
        Instant at = required(occurredAt);
        long actor = actor(transaction);
        Restriction current = findById(productId, id)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "展示限制不存在"));
        return release(current, actor, reason, basis, at);
    }

    /**
     * Releases the active restriction of one explicit source. The product and source are both
     * verified; a previously released source is an idempotent replay.
     */
    public ReleaseResult releaseLocked(WriteTransaction transaction, long productId, String sourceType,
                                       long sourceRef, String releaseReason, String releaseBasisRef,
                                       Instant occurredAt) {
        requireProductLock(transaction, productId);
        String type = sourceType(sourceType);
        long ref = positive(sourceRef, "来源标识");
        String reason = required(releaseReason, "解除原因");
        String basis = required(releaseBasisRef, "解除依据");
        Instant at = required(occurredAt);
        long actor = actor(transaction);
        Restriction active = lockActiveBySource(productId, type, ref);
        if (active != null) {
            return release(active, actor, reason, basis, at);
        }
        Restriction released = latestBySource(productId, type, ref)
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "展示限制不存在"));
        return new ReleaseResult(released.restrictionId(), released.sourceType(), released.sourceRefId(), true);
    }

    /** Active restrictions of one product, oldest first. */
    public List<Restriction> findActive(long productId) {
        positive(productId, "商品标识");
        return jdbc.sql("select " + COLUMNS + """
                          from product_display_restriction
                         where product_id = ? and released_at is null
                         order by restriction_id
                        """)
                .param(productId)
                .query(ProductDisplayRestrictions::row)
                .list();
    }

    /** The active restriction of one explicit source, if present. */
    public Optional<Restriction> findActive(long productId, String sourceType, long sourceRef) {
        positive(productId, "商品标识");
        String type = sourceType(sourceType);
        long ref = positive(sourceRef, "来源标识");
        return jdbc.sql("select " + COLUMNS + """
                          from product_display_restriction
                         where product_id = ? and source_type = ? and source_ref_id = ? and released_at is null
                        """)
                .param(productId).param(type).param(ref)
                .query(ProductDisplayRestrictions::row)
                .optional();
    }

    /** Resolves one restriction row by identifier, including released history. */
    public Optional<Restriction> find(long restrictionId) {
        positive(restrictionId, "限制标识");
        return jdbc.sql("select " + COLUMNS + " from product_display_restriction where restriction_id = ?")
                .param(restrictionId)
                .query(ProductDisplayRestrictions::row)
                .optional();
    }

    /**
     * Every product touched by one source, active rows first. Reversal plans use this to lock the
     * complete source scope even when an earlier retry already released one of the rows.
     */
    public List<Long> productIdsForSource(String sourceType, long sourceRef) {
        String type = sourceType(sourceType);
        long ref = positive(sourceRef, "来源标识");
        return jdbc.sql("""
                          select distinct product_id
                            from product_display_restriction
                           where source_type = ? and source_ref_id = ?
                           order by product_id
                        """)
                .param(type).param(ref)
                .query(Long.class).list();
    }

    public boolean hasActive(long productId) {
        positive(productId, "商品标识");
        return jdbc.sql("""
                        select exists (
                            select 1 from product_display_restriction
                             where product_id = ? and released_at is null)
                        """)
                .param(productId)
                .query(Boolean.class).single();
    }

    /** Whether one explicit source is active for the product. */
    public boolean hasActive(long productId, String sourceType, long sourceRef) {
        return findActive(productId, sourceType, sourceRef).isPresent();
    }

    /** All non-deleted products of a seller, ordered by product id for the account-ban path. */
    public List<Long> sellerProductIds(long sellerId) {
        positive(sellerId, "卖方账户标识");
        return jdbc.sql("""
                        select product_id from product
                         where seller_account_id = ? and deleted_at is null
                         order by product_id
                        """)
                .param(sellerId)
                .query(Long.class).list();
    }

    /** Batch active-product lookup for list projections; avoids one query per row. */
    public Set<Long> activeProductIds(Collection<Long> productIds) {
        if (productIds == null || productIds.isEmpty()) {
            return Set.of();
        }
        List<Long> ids = productIds.stream()
                .filter(id -> id != null && id > 0)
                .distinct()
                .toList();
        if (ids.isEmpty()) {
            return Set.of();
        }
        String placeholders = String.join(", ", java.util.Collections.nCopies(ids.size(), "?"));
        List<Long> found = jdbc.sql("""
                        select distinct product_id from product_display_restriction
                         where released_at is null and product_id in (""" + placeholders + ")")
                .params(ids.toArray())
                .query(Long.class).list();
        return Set.copyOf(new LinkedHashSet<>(found));
    }

    private ReleaseResult release(Restriction current, long actor, String reason, String basis, Instant at) {
        if (current.releasedAt() != null) {
            return new ReleaseResult(current.restrictionId(), current.sourceType(), current.sourceRefId(), true);
        }
        int changed = jdbc.sql("""
                        update product_display_restriction
                           set released_at = ?, released_by = ?, release_reason = ?, release_basis_ref = ?
                         where restriction_id = ? and released_at is null
                        """)
                .param(time(at)).param(actor).param(reason).param(basis).param(current.restrictionId())
                .update();
        if (changed == 0) {
            Restriction reloaded = findById(current.productId(), current.restrictionId())
                    .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "展示限制不存在"));
            if (reloaded.releasedAt() != null) {
                return new ReleaseResult(reloaded.restrictionId(), reloaded.sourceType(), reloaded.sourceRefId(),
                        true);
            }
            throw new BusinessError("STATE_CONFLICT", 409, "展示限制状态已变化");
        }
        return new ReleaseResult(current.restrictionId(), current.sourceType(), current.sourceRefId(), false);
    }

    private Optional<Long> activeId(long productId, String sourceType, long sourceRef) {
        return jdbc.sql("""
                        select restriction_id from product_display_restriction
                         where product_id = ? and source_type = ? and source_ref_id = ? and released_at is null
                        """)
                .param(productId).param(sourceType).param(sourceRef)
                .query(Long.class).optional();
    }

    private Optional<Restriction> findById(long productId, long restrictionId) {
        return jdbc.sql("select " + COLUMNS + """
                          from product_display_restriction
                         where restriction_id = ? and product_id = ?
                        """)
                .param(restrictionId).param(productId)
                .query(ProductDisplayRestrictions::row)
                .optional();
    }

    private Restriction lockActiveBySource(long productId, String sourceType, long sourceRef) {
        return jdbc.sql("select " + COLUMNS + """
                          from product_display_restriction
                         where product_id = ? and source_type = ? and source_ref_id = ? and released_at is null
                         order by restriction_id desc
                         limit 1
                         for update
                        """)
                .param(productId).param(sourceType).param(sourceRef)
                .query(ProductDisplayRestrictions::row)
                .optional()
                .orElse(null);
    }

    private Optional<Restriction> latestBySource(long productId, String sourceType, long sourceRef) {
        return jdbc.sql("select " + COLUMNS + """
                          from product_display_restriction
                         where product_id = ? and source_type = ? and source_ref_id = ?
                         order by restriction_id desc
                         limit 1
                        """)
                .param(productId).param(sourceType).param(sourceRef)
                .query(ProductDisplayRestrictions::row)
                .optional();
    }

    private boolean productExists(long productId) {
        return jdbc.sql("select exists (select 1 from product where product_id = ? and deleted_at is null)")
                .param(productId)
                .query(Boolean.class).single();
    }

    private static void requireProductLock(WriteTransaction transaction, long productId) {
        if (transaction == null) {
            throw new IllegalStateException("A write transaction is required");
        }
        transaction.requireLocked(new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(productId)));
    }

    private static long actor(WriteTransaction transaction) {
        try {
            long actor = Long.parseLong(transaction.context().actorId());
            if (actor > 0) {
                return actor;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the explicit error below.
        }
        throw new BusinessError("ACTION_NOT_ALLOWED", 403, "展示限制操作缺少账户执行者");
    }

    private static String sourceType(String value) {
        String type = value == null ? "" : value.trim();
        if (!SOURCE_TYPES.contains(type)) {
            throw new BusinessError("INPUT_INVALID", 422, "展示限制来源无效");
        }
        return type;
    }

    private static long positive(long value, String label) {
        if (value <= 0) {
            throw new BusinessError("INPUT_INVALID", 422, label + "无效");
        }
        return value;
    }

    private static String required(String value, String label) {
        String text = value == null ? "" : value.trim();
        if (text.isEmpty()) {
            throw new BusinessError("INPUT_INVALID", 422, label + "无效");
        }
        return text;
    }

    private static Instant required(Instant value) {
        if (value == null) {
            throw new BusinessError("INPUT_INVALID", 422, "发生时间无效");
        }
        return value;
    }

    private static OffsetDateTime time(Instant value) {
        return OffsetDateTime.ofInstant(value, ZoneOffset.UTC);
    }

    private static Restriction row(ResultSet row, int index) throws SQLException {
        return new Restriction(row.getLong("restriction_id"), row.getLong("product_id"),
                row.getString("source_type"), row.getLong("source_ref_id"), row.getString("reason"),
                row.getString("basis_ref"), row.getLong("created_by"), instant(row, "created_at"),
                instant(row, "released_at"), nullableLong(row, "released_by"), row.getString("release_reason"),
                row.getString("release_basis_ref"));
    }

    private static Long nullableLong(ResultSet row, String column) throws SQLException {
        long value = row.getLong(column);
        return row.wasNull() ? null : value;
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        OffsetDateTime value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    /** Outcome of an idempotent apply; {@code alreadyActive} means this call changed nothing. */
    public record ApplyResult(long restrictionId, String sourceType, long sourceRefId, boolean alreadyActive) {
    }

    /** Outcome of an idempotent release; {@code alreadyReleased} means this call changed nothing. */
    public record ReleaseResult(long restrictionId, String sourceType, long sourceRefId, boolean alreadyReleased) {
    }

    public record Restriction(long restrictionId, long productId, String sourceType, long sourceRefId,
                              String reason, String basisRef, long createdBy, Instant createdAt,
                              Instant releasedAt, Long releasedBy, String releaseReason, String releaseBasisRef) {
        public boolean active() {
            return releasedAt == null;
        }
    }
}
