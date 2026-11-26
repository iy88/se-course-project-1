package io.github.iy88.project1.trade.persistence;

import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Pageable;
import org.springframework.data.repository.Repository;

interface TradeHistoryRows extends Repository<TradeHistoryRow, Long> {
    TradeHistoryRow save(TradeHistoryRow row);

    Optional<TradeHistoryRow> findById(long id);

    Optional<TradeHistoryRow> findByFreezeIdAndAction(long freezeId, String action);

    List<TradeHistoryRow> findByTradeIdOrderById(long tradeId, Pageable page);
}
