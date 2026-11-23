package io.github.iy88.project1.trade.persistence;

import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.repository.Repository;

interface TradeHistoryRows extends Repository<TradeHistoryRow, Long> {
    TradeHistoryRow save(TradeHistoryRow row);

    List<TradeHistoryRow> findByTradeIdOrderById(long tradeId, Pageable page);
}
