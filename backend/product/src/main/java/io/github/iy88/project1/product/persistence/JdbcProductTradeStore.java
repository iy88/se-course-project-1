package io.github.iy88.project1.product.persistence;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.product.application.ProductTradeStore;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Service
@Profile("infrastructure")
public class JdbcProductTradeStore implements ProductTradeStore {
    private static final String COLUMNS = """
            select p.product_id, p.seller_account_id, p.content_version, p.lifecycle_state,
                   p.occupied_by_trade_id, p.title, p.description, p.price_cents
              from product p
             where p.product_id = ? and p.deleted_at is null
            """;

    private final JdbcClient jdbc;

    public JdbcProductTradeStore(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<TradeProduct> read(long productId) {
        return jdbc.sql(COLUMNS).param(productId).query(this::row).optional().map(this::enrich);
    }

    @Override
    public Optional<TradeProduct> lock(long productId) {
        requireTransaction();
        return jdbc.sql(COLUMNS + " for update").param(productId).query(this::row).optional()
                .map(this::enrich);
    }

    @Override
    public void acquire(long productId, long tradeId, Instant now) {
        requireTransaction();
        int changed = jdbc.sql("""
                        update product
                           set lifecycle_state = 'in_trade', occupied_by_trade_id = ?, updated_at = ?
                         where product_id = ? and lifecycle_state = 'public'
                           and occupied_by_trade_id is null and deleted_at is null
                        """)
                .param(tradeId).param(at(now)).param(productId).update();
        if (changed == 0) {
            throw new BusinessError("PRODUCT_NOT_AVAILABLE", 409, "商品当前不可交易");
        }
    }

    @Override
    public void release(long productId, long tradeId, Instant now) {
        requireTransaction();
        int changed = jdbc.sql("""
                        update product
                           set lifecycle_state = 'off_shelf', occupied_by_trade_id = null, updated_at = ?
                         where product_id = ? and occupied_by_trade_id = ?
                        """)
                .param(at(now)).param(productId).param(tradeId).update();
        if (changed == 0) {
            throw new BusinessError("OCCUPANCY_NOT_HELD", 409, "交易未持有商品占用");
        }
    }

    private TradeProduct row(ResultSet row, int index) throws SQLException {
        return new TradeProduct(row.getLong("product_id"), row.getLong("seller_account_id"),
                row.getInt("content_version"), row.getString("lifecycle_state"),
                row.getObject("occupied_by_trade_id", Long.class), row.getString("title"),
                row.getString("description"), row.getLong("price_cents"), List.of(), List.of());
    }

    private TradeProduct enrich(TradeProduct product) {
        List<String> categoryNames = jdbc.sql("""
                        select n.name
                          from product_category pc
                          join category_name n on n.category_id = pc.category_id
                         where pc.product_id = ? and pc.removed_at is null
                           and n.deactivated_at is null and n.name_kind = 'main'
                         order by pc.category_id, n.category_name_id
                        """)
                .param(product.productId()).query(String.class).list();
        List<Long> imageFileIds = jdbc.sql("""
                        select file_id
                          from file_reference
                         where target_type = 'product' and target_id = ? and slot = 'image'
                         order by reference_id
                        """)
                .param(product.productId()).query(Long.class).list();
        return new TradeProduct(product.productId(), product.sellerId(), product.contentVersion(),
                product.lifecycleState(), product.occupiedByTradeId(), product.title(),
                product.description(), product.priceCents(), categoryNames, imageFileIds);
    }

    private static OffsetDateTime at(Instant instant) {
        return OffsetDateTime.ofInstant(instant, ZoneOffset.UTC);
    }

    private static void requireTransaction() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("Product trade writes require the caller's transaction");
        }
    }
}
