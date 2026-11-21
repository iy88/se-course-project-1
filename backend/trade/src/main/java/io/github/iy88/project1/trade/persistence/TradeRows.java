package io.github.iy88.project1.trade.persistence;

import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeStatus;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.Repository;

interface TradeRows extends Repository<TradeRow, Long> {
    String NEWEST_FIRST = "t.updatedAt desc, t.id desc";
    String MATCHING_ACCOUNT_TRADES = """
            from TradeRow t
            where ((:role <> 'seller' and t.buyerId = :accountId)
                or (:role <> 'buyer' and t.sellerId = :accountId))
                and t.status in :statuses
            """;

    TradeRow save(TradeRow row);

    // A DTO projection reads the database again after native lifecycle updates in the same transaction.
    Optional<Trade> findProjectedById(long id);

    @Query("select t.id " + MATCHING_ACCOUNT_TRADES + " order by " + NEWEST_FIRST
            + " offset :offset rows fetch first :limit rows only")
    List<Long> pageIds(long accountId, String role, Collection<TradeStatus> statuses, int limit, int offset);

    // Hibernate binds OFFSET as an int. Row numbers keep the existing long-offset API range.
    @Query("select ranked.id from (select t.id as id, row_number() over (order by " + NEWEST_FIRST
            + ") as rowNumber " + MATCHING_ACCOUNT_TRADES + """
            ) ranked where ranked.rowNumber > :offset and ranked.rowNumber <= :end
            order by ranked.rowNumber
            """)
    List<Long> pageIdsByPosition(long accountId, String role, Collection<TradeStatus> statuses, long offset, long end);

    @Query("select count(t) " + MATCHING_ACCOUNT_TRADES)
    long countMatching(long accountId, String role, Collection<TradeStatus> statuses);
}
