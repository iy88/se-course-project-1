package io.github.iy88.project1.product.persistence;

import io.github.iy88.project1.product.application.ProductInteractionStore;
import io.github.iy88.project1.product.domain.ProductComment;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.OptionalLong;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/** Explicit SQL for product comments and favourites; rows stay inside the caller's transaction. */
@Repository
@Profile("infrastructure")
public class JdbcProductInteractionStore implements ProductInteractionStore {
    private static final String COMMENT_COLUMNS = """
            comment_id, product_id, author_account_id, parent_comment_id, body, created_at,
            deleted_at, removed_at, removed_reason, basis_ref
            """;

    private final JdbcClient jdbc;

    public JdbcProductInteractionStore(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public long insertComment(long productId, long authorAccountId, Long parentCommentId, String body, Instant now) {
        return jdbc.sql("""
                        insert into product_comment
                            (product_id, author_account_id, parent_comment_id, body, created_at)
                        values (?, ?, ?, ?, ?)
                        returning comment_id
                        """)
                .param(productId).param(authorAccountId).param(parentCommentId).param(body)
                .param(OffsetDateTime.ofInstant(now, java.time.ZoneOffset.UTC))
                .query(Long.class).single();
    }

    @Override
    public Optional<ProductComment> comment(long commentId) {
        return jdbc.sql("select " + COMMENT_COLUMNS + " from product_comment where comment_id = ?")
                .param(commentId)
                .query((rs, row) -> map(rs))
                .optional();
    }

    @Override
    public Optional<ProductComment> lockComment(long commentId) {
        return jdbc.sql("select " + COMMENT_COLUMNS + " from product_comment where comment_id = ? for update")
                .param(commentId)
                .query((rs, row) -> map(rs))
                .optional();
    }

    @Override
    public List<ProductComment> topLevelComments(long productId, Scope scope, long viewerId, int limit, long offset) {
        var sql = new StringBuilder("select " + COMMENT_COLUMNS
                + " from product_comment where product_id = ? and parent_comment_id is null");
        var args = new java.util.ArrayList<Object>();
        args.add(productId);
        appendScope(sql, args, scope, viewerId);
        sql.append(" order by created_at desc, comment_id desc limit ? offset ?");
        args.add(limit);
        args.add(offset);
        return jdbc.sql(sql.toString()).params(args.toArray())
                .query((rs, row) -> map(rs)).list();
    }

    @Override
    public long countTopLevelComments(long productId, Scope scope, long viewerId) {
        var sql = new StringBuilder(
                "select count(*) from product_comment where product_id = ? and parent_comment_id is null");
        var args = new java.util.ArrayList<Object>();
        args.add(productId);
        appendScope(sql, args, scope, viewerId);
        return jdbc.sql(sql.toString()).params(args.toArray()).query(Long.class).single();
    }

    @Override
    public long countNewerTopLevelComments(ProductComment anchor, Scope scope, long viewerId) {
        var sql = new StringBuilder("""
                select count(*) from product_comment where product_id = ? and parent_comment_id is null
                  and (created_at, comment_id) > (?, ?)
                """);
        var args = new java.util.ArrayList<Object>(List.of(anchor.productId(),
                OffsetDateTime.ofInstant(anchor.createdAt(), java.time.ZoneOffset.UTC), anchor.commentId()));
        appendScope(sql, args, scope, viewerId);
        return jdbc.sql(sql.toString()).params(args.toArray()).query(Long.class).single();
    }

    @Override
    public boolean hasCommentBy(long productId, long authorId) {
        return jdbc.sql("select exists (select 1 from product_comment where product_id = ? and author_account_id = ?)")
                .param(productId).param(authorId).query(Boolean.class).single();
    }

    @Override
    public List<ProductComment> replies(long productId, List<Long> parentIds, Scope scope, long viewerId) {
        if (parentIds.isEmpty()) {
            return List.of();
        }
        var sql = new StringBuilder("select " + COMMENT_COLUMNS
                + " from product_comment where product_id = ? and parent_comment_id in (");
        var args = new java.util.ArrayList<Object>();
        args.add(productId);
        for (int index = 0; index < parentIds.size(); index++) {
            sql.append(index == 0 ? "?" : ", ?");
            args.add(parentIds.get(index));
        }
        sql.append(')');
        if (scope == Scope.PUBLIC) {
            sql.append(" and deleted_at is null and removed_at is null");
        } else if (scope == Scope.AUTHOR) {
            sql.append(" and (deleted_at is null and removed_at is null or author_account_id = ?)");
            args.add(viewerId);
        }
        sql.append(" order by created_at asc, comment_id asc");
        return jdbc.sql(sql.toString()).params(args.toArray())
                .query((rs, row) -> map(rs)).list();
    }

    @Override
    public boolean markDeletedByAuthor(long commentId, Instant now) {
        return jdbc.sql("""
                        update product_comment set deleted_at = ?
                         where comment_id = ? and deleted_at is null and removed_at is null
                        """)
                .param(OffsetDateTime.ofInstant(now, java.time.ZoneOffset.UTC)).param(commentId)
                .update() == 1;
    }

    @Override
    public boolean markRemovedByAdmin(long commentId, long adminId, String reason, String basisRef, Instant now) {
        return jdbc.sql("""
                        update product_comment
                           set removed_at = ?, removed_by_admin_id = ?, removed_reason = ?, basis_ref = ?
                         where comment_id = ? and removed_at is null
                        """)
                .param(OffsetDateTime.ofInstant(now, java.time.ZoneOffset.UTC)).param(adminId)
                .param(reason).param(basisRef).param(commentId).update() == 1;
    }

    @Override
    public long countCommentsSince(long authorId, Instant since) {
        return jdbc.sql("""
                        select count(*) from product_comment
                         where author_account_id = ? and created_at > ?
                        """)
                .param(authorId).param(OffsetDateTime.ofInstant(since, java.time.ZoneOffset.UTC))
                .query(Long.class).single();
    }

    @Override
    public OptionalLong productIdOfComment(long commentId) {
        return jdbc.sql("select product_id from product_comment where comment_id = ?")
                .param(commentId).query(Long.class).optional()
                .map(OptionalLong::of).orElseGet(OptionalLong::empty);
    }

    @Override
    public Optional<FavoriteRow> favorite(long accountId, long productId) {
        return jdbc.sql("""
                        select favorite_id, product_id, created_at from product_favorite
                        where account_id = ? and product_id = ?
                        """)
                .param(accountId).param(productId)
                .query((row, index) -> favoriteRow(row))
                .optional();
    }

    private static final String OWNED_FAVORITES = """
                  from product_favorite f
                  join product p on p.product_id = f.product_id
                 where f.account_id = :account
                   and (cast(:state as text) is null or :state = case
                       when p.deleted_at is null and p.lifecycle_state in ('public', 'in_trade')
                            and not exists (select 1 from product_display_restriction r
                                             where r.product_id = p.product_id and r.released_at is null)
                       then 'valid' else 'invalid' end)
                """;

    @Override
    public List<FavoriteRow> favorites(long accountId, String state, int limit, long offset) {
        return jdbc.sql("select f.favorite_id, f.product_id, f.created_at" + OWNED_FAVORITES
                        + " order by f.created_at desc, f.favorite_id desc limit :limit offset :offset")
                .param("account", accountId).param("state", state, java.sql.Types.VARCHAR)
                .param("limit", limit).param("offset", offset)
                .query((row, index) -> favoriteRow(row))
                .list();
    }

    @Override
    public long countFavorites(long accountId, String state) {
        return jdbc.sql("select count(*)" + OWNED_FAVORITES)
                .param("account", accountId).param("state", state, java.sql.Types.VARCHAR)
                .query(Long.class).single();
    }

    private static FavoriteRow favoriteRow(java.sql.ResultSet row) throws java.sql.SQLException {
        return new FavoriteRow(row.getLong("favorite_id"), row.getLong("product_id"), instant(row, "created_at"));
    }

    @Override
    public boolean insertFavorite(long accountId, long productId, Instant now) {
        return jdbc.sql("""
                        insert into product_favorite (account_id, product_id, created_at)
                        values (?, ?, ?)
                        on conflict (account_id, product_id) do nothing
                        """)
                .param(accountId).param(productId)
                .param(OffsetDateTime.ofInstant(now, java.time.ZoneOffset.UTC)).update() == 1;
    }

    @Override
    public boolean deleteFavorite(long accountId, long productId) {
        return jdbc.sql("delete from product_favorite where account_id = ? and product_id = ?")
                .param(accountId).param(productId).update() == 1;
    }

    private static void appendScope(StringBuilder sql, List<Object> args, Scope scope, long viewerId) {
        switch (scope) {
            case PUBLIC -> sql.append(" and deleted_at is null and removed_at is null");
            case AUTHOR -> {
                sql.append(" and author_account_id = ?");
                args.add(viewerId);
            }
            case CASE -> {
                // The claimed manager reads the case's necessary scope including removal facts.
            }
        }
    }

    private static ProductComment map(ResultSet rs) throws SQLException {
        long parent = rs.getLong("parent_comment_id");
        Long parentCommentId = rs.wasNull() ? null : parent;
        return new ProductComment(rs.getLong("comment_id"), rs.getLong("product_id"),
                rs.getLong("author_account_id"), parentCommentId, rs.getString("body"),
                instant(rs, "created_at"), instant(rs, "deleted_at"), instant(rs, "removed_at"),
                rs.getString("removed_reason"), rs.getString("basis_ref"));
    }

    private static Instant instant(ResultSet rs, String column) throws SQLException {
        OffsetDateTime value = rs.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }
}
