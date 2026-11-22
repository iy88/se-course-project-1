package io.github.iy88.project1.trade.persistence;

import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.PageRequest;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
@Profile("infrastructure & !dependency-probe & !file-probe")
public class TradeRepository {
    private final JdbcClient jdbc;
    private final TradeRows trades;
    private final AgreementDecisionRows agreementDecisions;
    private final TradeHistoryRows histories;

    TradeRepository(JdbcClient jdbc, TradeRows trades, AgreementDecisionRows agreementDecisions,
                    TradeHistoryRows histories) {
        this.jdbc = jdbc;
        this.trades = trades;
        this.agreementDecisions = agreementDecisions;
        this.histories = histories;
    }

    public Optional<Trade> find(long tradeId) {
        return trades.findProjectedById(tradeId);
    }

    public Trade lockTrade(WriteTransaction transaction, long tradeId) {
        var result = new AtomicReference<Trade>();
        transaction.lock(new LockPlan.Key(LockPlan.Domain.TRADE, List.of(tradeId)), () -> result.set(
                jdbc.sql("SELECT * FROM trade WHERE id = :id FOR UPDATE").param("id", tradeId)
                        .query((row, index) -> trade(row)).optional().orElse(null)));
        if (result.get() == null) {
            throw Trade.notVisible();
        }
        return result.get();
    }

    public long insertTrade(long productId, long buyerId, long sellerId, String note, Instant now) {
        return trades.save(new TradeRow(productId, buyerId, sellerId, note, now)).id();
    }

    public void touch(long tradeId, Instant now) {
        jdbc.sql("UPDATE trade SET updated_at = :now WHERE id = :id")
                .param("now", time(now)).param("id", tradeId).update();
    }

    public void save(Trade trade) {
        jdbc.sql("""
                UPDATE trade SET status = :status, request_note = :note, active_agreement_id = :agreement,
                    version = :version, close_reason = :close, terminal_reason = :terminal,
                    responded_at = :responded, ended_at = :ended, updated_at = :updated
                WHERE id = :id
                """).param("status", trade.status().value()).param("note", trade.requestNote())
                .param("agreement", trade.activeAgreementId()).param("version", trade.version())
                .param("close", trade.closeReason()).param("terminal", trade.terminalReason())
                .param("responded", time(trade.respondedAt())).param("ended", time(trade.endedAt()))
                .param("updated", time(trade.updatedAt())).param("id", trade.id()).update();
    }

    public List<Long> pendingTradeIds(long productId, long excluding) {
        return jdbc.sql("""
                SELECT id FROM trade WHERE product_id = :product AND status = 'pending_acceptance'
                    AND id <> :excluding ORDER BY id
                """).param("product", productId).param("excluding", excluding).query(Long.class).list();
    }

    public List<Long> pendingTradeIdsForAccount(long accountId) {
        return jdbc.sql("""
                SELECT id FROM trade WHERE status = 'pending_acceptance'
                    AND (buyer_id = :account OR seller_id = :account) ORDER BY id
                """).param("account", accountId).query(Long.class).list();
    }

    public List<Long> pendingTradeIdsForProduct(long productId) {
        return jdbc.sql("SELECT id FROM trade WHERE product_id = :product "
                        + "AND status = 'pending_acceptance' ORDER BY id")
                .param("product", productId).query(Long.class).list();
    }

    public List<Long> activeTradeIdsForAccount(long accountId) {
        return jdbc.sql("""
                SELECT id FROM trade WHERE status IN ('in_progress', 'disputed', 'abnormal')
                    AND (buyer_id = :account OR seller_id = :account) ORDER BY id
                """).param("account", accountId).query(Long.class).list();
    }

    public List<Long> tradeIdsForAccount(long accountId) {
        return jdbc.sql("""
                SELECT id FROM trade WHERE buyer_id = :account OR seller_id = :account ORDER BY id
                """).param("account", accountId).query(Long.class).list();
    }

    public AccountPage pageForAccount(long accountId, String role, List<TradeStatus> statuses, int limit,
                                      long offset) {
        var matchingStatuses = statuses.isEmpty() ? EnumSet.allOf(TradeStatus.class) : statuses;
        var ids = offset <= Integer.MAX_VALUE
                ? trades.pageIds(accountId, role, matchingStatuses, limit, (int) offset)
                : trades.pageIdsByPosition(accountId, role, matchingStatuses, offset, offset + limit);
        return new AccountPage(ids, trades.countMatching(accountId, role, matchingStatuses));
    }

    public record AccountPage(List<Long> ids, long total) {}

    public Optional<TradeModels.Snapshot> snapshot(long tradeId) {
        return jdbc.sql("SELECT * FROM trade_item_snapshot WHERE trade_id = :trade").param("trade", tradeId)
                .query((row, index) -> new TradeModels.Snapshot(row.getLong("trade_id"), row.getLong("product_id"),
                        row.getString("title"), row.getString("description"), row.getLong("price_cents"),
                        stringArray(row, "category_names"), longArray(row, "image_file_ids"),
                        instant(row, "captured_at"))).optional();
    }

    public void insertSnapshot(TradeModels.Snapshot snapshot) {
        jdbc.sql("""
                INSERT INTO trade_item_snapshot (trade_id, product_id, title, description, price_cents,
                    category_names, image_file_ids, captured_at)
                VALUES (:trade, :product, :title, :description, :price, CAST(:categories AS text[]),
                    CAST(:images AS bigint[]), :captured)
                """).param("trade", snapshot.tradeId()).param("product", snapshot.productId())
                .param("title", snapshot.title()).param("description", snapshot.description())
                .param("price", snapshot.priceCents()).param("categories", textArray(snapshot.categoryNames()))
                .param("images", longArrayLiteral(snapshot.imageFileIds())).param("captured", time(snapshot.capturedAt()))
                .update();
    }

    public Optional<TradeModels.Agreement> currentAgreement(long tradeId) {
        return agreement("SELECT * FROM agreement_version WHERE trade_id = :trade AND status = 'effective'", tradeId);
    }

    public Optional<TradeModels.Agreement> pendingAgreement(long tradeId) {
        return agreement("SELECT * FROM agreement_version WHERE trade_id = :trade AND status = 'proposed'", tradeId);
    }

    public Optional<TradeModels.Agreement> agreement(long agreementId) {
        return jdbc.sql("SELECT * FROM agreement_version WHERE id = :id").param("id", agreementId)
                .query((row, index) -> agreementRow(row)).optional();
    }

    private Optional<TradeModels.Agreement> agreement(String sql, long tradeId) {
        return jdbc.sql(sql).param("trade", tradeId).query((row, index) -> agreementRow(row)).optional();
    }

    public List<TradeModels.Agreement> agreements(long tradeId) {
        return jdbc.sql("SELECT * FROM agreement_version WHERE trade_id = :trade ORDER BY id")
                .param("trade", tradeId).query((row, index) -> agreementRow(row)).list();
    }

    public long nextAgreementVersion(long tradeId) {
        return jdbc.sql("SELECT coalesce(max(version_no), 0) + 1 FROM agreement_version WHERE trade_id = :trade")
                .param("trade", tradeId).query(Integer.class).single();
    }

    public long insertAgreement(TradeModels.Agreement agreement) {
        return jdbc.sql("""
                INSERT INTO agreement_version (trade_id, base_agreement_id, version_no, status, proposed_by,
                    delivery_at, delivery_place_text, delivery_method, amount_cents, payment_method,
                    payment_timing, proposed_at, business_event_id)
                VALUES (:trade, :base, :version, :status, :proposer, :delivery, :place, :method, :amount,
                    :payment, :timing, :proposed, :event)
                RETURNING id
                """).param("trade", agreement.tradeId()).param("base", agreement.baseAgreementId())
                .param("version", agreement.versionNo()).param("status", agreement.status().value())
                .param("proposer", agreement.proposedBy()).param("delivery", time(agreement.deliveryAt()))
                .param("place", agreement.deliveryPlaceText()).param("method", agreement.deliveryMethod())
                .param("amount", agreement.amountCents()).param("payment", agreement.paymentMethod())
                .param("timing", agreement.paymentTiming()).param("proposed", time(agreement.proposedAt()))
                .param("event", agreement.businessEventId()).query(Long.class).single();
    }

    public void setAgreementStatus(long agreementId, TradeVocabulary.AgreementStatus status) {
        jdbc.sql("UPDATE agreement_version SET status = :status WHERE id = :id")
                .param("status", status.value()).param("id", agreementId).update();
    }

    public void supersedeEffective(long tradeId, long exceptAgreementId) {
        jdbc.sql("""
                UPDATE agreement_version SET status = 'superseded'
                WHERE trade_id = :trade AND status = 'effective' AND id <> :except
                """).param("trade", tradeId).param("except", exceptAgreementId).update();
    }

    public long insertAgreementDecision(TradeModels.Decision decision) {
        return agreementDecisions.save(new AgreementDecisionRow(decision)).id();
    }

    public Optional<TradeModels.Cancellation> pendingCancellation(long tradeId) {
        return jdbc.sql("SELECT * FROM cancellation_proposal WHERE trade_id = :trade AND status = 'pending'")
                .param("trade", tradeId).query((row, index) -> cancellationRow(row)).optional();
    }

    public Optional<TradeModels.Cancellation> cancellation(long cancellationId) {
        return jdbc.sql("SELECT * FROM cancellation_proposal WHERE id = :id").param("id", cancellationId)
                .query((row, index) -> cancellationRow(row)).optional();
    }

    public long insertCancellation(TradeModels.Cancellation cancellation) {
        return jdbc.sql("""
                INSERT INTO cancellation_proposal (trade_id, proposed_by, mode, reason, status, proposed_at,
                    business_event_id)
                VALUES (:trade, :proposer, :mode, :reason, :status, :proposed, :event) RETURNING id
                """).param("trade", cancellation.tradeId()).param("proposer", cancellation.proposedBy())
                .param("mode", cancellation.mode().value()).param("reason", cancellation.reason())
                .param("status", cancellation.status().value()).param("proposed", time(cancellation.proposedAt()))
                .param("event", cancellation.businessEventId()).query(Long.class).single();
    }

    public void setCancellationStatus(long cancellationId, TradeVocabulary.CancellationStatus status) {
        jdbc.sql("UPDATE cancellation_proposal SET status = :status WHERE id = :id")
                .param("status", status.value()).param("id", cancellationId).update();
    }

    public long insertCancellationDecision(TradeModels.CancellationDecision decision) {
        return jdbc.sql("""
                INSERT INTO cancellation_decision (cancellation_id, decision, actor_id, decided_at, business_event_id)
                VALUES (:cancellation, :decision, :actor, :decided, :event) RETURNING id
                """).param("cancellation", decision.cancellationId()).param("decision", decision.decision().value())
                .param("actor", decision.actorId()).param("decided", time(decision.decidedAt()))
                .param("event", decision.businessEventId()).query(Long.class).single();
    }

    public Optional<TradeModels.Dispute> openDispute(long tradeId) {
        return jdbc.sql("SELECT * FROM trade_dispute WHERE trade_id = :trade AND status = 'open'")
                .param("trade", tradeId).query((row, index) -> disputeRow(row)).optional();
    }

    public Optional<TradeModels.Dispute> dispute(long disputeId) {
        return jdbc.sql("SELECT * FROM trade_dispute WHERE id = :id").param("id", disputeId)
                .query((row, index) -> disputeRow(row)).optional();
    }

    public List<TradeModels.Dispute> disputes(long tradeId) {
        return jdbc.sql("SELECT * FROM trade_dispute WHERE trade_id = :trade ORDER BY id")
                .param("trade", tradeId).query((row, index) -> disputeRow(row)).list();
    }

    public long insertDispute(long tradeId, long initiatorId, String statement, Instant now) {
        return jdbc.sql("""
                INSERT INTO trade_dispute (trade_id, initiator_id, statement, status, opened_at)
                VALUES (:trade, :initiator, :statement, 'open', :now) RETURNING id
                """).param("trade", tradeId).param("initiator", initiatorId).param("statement", statement)
                .param("now", time(now)).query(Long.class).single();
    }

    public void resolveDispute(long disputeId, TradeVocabulary.ResolutionMode mode, long resolvedBy, Long caseId,
                               Instant now) {
        jdbc.sql("""
                UPDATE trade_dispute SET status = 'resolved', resolution_mode = :mode, resolved_by = :by,
                    case_id = :case, resolved_at = :now WHERE id = :id
                """).param("mode", mode.value()).param("by", resolvedBy).param("case", caseId).param("now", time(now))
                .param("id", disputeId).update();
    }

    public void terminateOpenDisputes(long tradeId, Instant now) {
        jdbc.sql("""
                UPDATE trade_dispute SET status = 'terminated', resolved_at = :now
                WHERE trade_id = :trade AND status = 'open'
                """).param("now", time(now)).param("trade", tradeId).update();
    }

    public List<TradeModels.ResolutionConfirmation> resolutionConfirmations(long disputeId) {
        return jdbc.sql("SELECT * FROM dispute_resolution_confirmation WHERE dispute_id = :dispute ORDER BY id")
                .param("dispute", disputeId).query((row, index) -> new TradeModels.ResolutionConfirmation(row.getLong("id"),
                        row.getLong("dispute_id"), row.getLong("confirmer_id"), instant(row, "confirmed_at"),
                        row.getObject("business_event_id", UUID.class))).list();
    }

    public long insertResolutionConfirmation(TradeModels.ResolutionConfirmation confirmation) {
        return jdbc.sql("""
                INSERT INTO dispute_resolution_confirmation (dispute_id, confirmer_id, confirmed_at, business_event_id)
                VALUES (:dispute, :confirmer, :confirmed, :event) RETURNING id
                """).param("dispute", confirmation.disputeId()).param("confirmer", confirmation.confirmerId())
                .param("confirmed", time(confirmation.confirmedAt()))
                .param("event", confirmation.businessEventId()).query(Long.class).single();
    }

    public List<TradeModels.Confirmation> currentConfirmations(long tradeId) {
        return jdbc.sql("""
                SELECT * FROM trade_confirmation WHERE trade_id = :trade AND invalidated_at IS NULL ORDER BY id
                """).param("trade", tradeId).query((row, index) -> confirmationRow(row)).list();
    }

    public List<TradeModels.Confirmation> confirmations(long tradeId) {
        return jdbc.sql("SELECT * FROM trade_confirmation WHERE trade_id = :trade ORDER BY id")
                .param("trade", tradeId).query((row, index) -> confirmationRow(row)).list();
    }

    public long insertConfirmation(TradeModels.Confirmation confirmation) {
        return jdbc.sql("""
                INSERT INTO trade_confirmation (trade_id, agreement_id, confirmer_id, note, submitted_at,
                    business_event_id)
                VALUES (:trade, :agreement, :confirmer, :note, :submitted, :event) RETURNING id
                """).param("trade", confirmation.tradeId()).param("agreement", confirmation.agreementId())
                .param("confirmer", confirmation.confirmerId()).param("note", confirmation.note())
                .param("submitted", time(confirmation.submittedAt()))
                .param("event", confirmation.businessEventId()).query(Long.class).single();
    }

    public void invalidateConfirmations(long tradeId, TradeVocabulary.InvalidationReason reason, Instant now) {
        jdbc.sql("""
                UPDATE trade_confirmation SET invalidated_at = :now, invalidation_reason = :reason
                WHERE trade_id = :trade AND invalidated_at IS NULL
                """).param("now", time(now)).param("reason", reason.value()).param("trade", tradeId).update();
    }

    public Optional<TradeModels.Wait> waitFor(long tradeId) {
        return jdbc.sql("SELECT * FROM confirmation_wait WHERE trade_id = :trade").param("trade", tradeId)
                .query((row, index) -> new TradeModels.Wait(row.getLong("trade_id"), instant(row, "started_at"),
                        instant(row, "active_since"), row.getInt("accumulated_seconds"), row.getInt("wait_seconds"),
                        row.getString("policy_version"), instant(row, "ended_at"),
                        enumValue(row, "end_reason", TradeVocabulary.WaitEndReason::from))).optional();
    }

    public void saveWait(long tradeId, TradeModels.Wait wait) {
        jdbc.sql("""
                INSERT INTO confirmation_wait (trade_id, started_at, active_since, accumulated_seconds,
                    wait_seconds, policy_version, ended_at, end_reason)
                VALUES (:trade, :started, :active, :accumulated, :wait, :policy, :ended, :reason)
                ON CONFLICT (trade_id) DO UPDATE SET started_at = EXCLUDED.started_at,
                    active_since = EXCLUDED.active_since, accumulated_seconds = EXCLUDED.accumulated_seconds,
                    wait_seconds = EXCLUDED.wait_seconds, policy_version = EXCLUDED.policy_version,
                    ended_at = EXCLUDED.ended_at, end_reason = EXCLUDED.end_reason
                """).param("trade", tradeId).param("started", time(wait.startedAt()))
                .param("active", time(wait.activeSince())).param("accumulated", wait.accumulatedSeconds())
                .param("wait", wait.waitSeconds()).param("policy", wait.policyVersion())
                .param("ended", time(wait.endedAt()))
                .param("reason", wait.endReason() == null ? null : wait.endReason().value()).update();
    }

    public List<TradeModels.Freeze> activeFreezes(long tradeId) {
        return jdbc.sql("""
                SELECT * FROM trade_freeze WHERE trade_id = :trade AND ended_at IS NULL ORDER BY id
                """).param("trade", tradeId).query((row, index) -> freezeRow(row)).list();
    }

    public Optional<TradeModels.Freeze> freeze(long freezeId) {
        return jdbc.sql("SELECT * FROM trade_freeze WHERE id = :id").param("id", freezeId)
                .query((row, index) -> freezeRow(row)).optional();
    }

    public boolean pairFrozen(long firstAccountId, long secondAccountId) {
        return jdbc.sql("""
                SELECT EXISTS (
                    SELECT 1 FROM trade t JOIN trade_freeze f ON f.trade_id = t.id
                    WHERE f.ended_at IS NULL AND (
                        (t.buyer_id = :first AND t.seller_id = :second)
                        OR (t.buyer_id = :second AND t.seller_id = :first)
                    )
                )
                """).param("first", firstAccountId).param("second", secondAccountId).query(Boolean.class).single();
    }

    public long insertFreeze(long tradeId, TradeVocabulary.FreezeSource source, Long sourceRef, String reason,
                             Instant now) {
        return jdbc.sql("""
                INSERT INTO trade_freeze (trade_id, source, source_ref, reason, started_at)
                VALUES (:trade, :source, :ref, :reason, :now) RETURNING id
                """).param("trade", tradeId).param("source", source.value()).param("ref", sourceRef)
                .param("reason", reason).param("now", time(now)).query(Long.class).single();
    }

    public void endFreeze(long freezeId, Long endedBy, Instant now) {
        jdbc.sql("UPDATE trade_freeze SET ended_at = :now, ended_by = :by WHERE id = :id AND ended_at IS NULL")
                .param("now", time(now)).param("by", endedBy).param("id", freezeId).update();
    }

    public void endAllFreezes(long tradeId, Instant now) {
        jdbc.sql("UPDATE trade_freeze SET ended_at = :now WHERE trade_id = :trade AND ended_at IS NULL")
                .param("now", time(now)).param("trade", tradeId).update();
    }

    public long insertHistory(TradeModels.History history) {
        return histories.save(new TradeHistoryRow(history)).id();
    }

    public List<TradeModels.History> history(long tradeId, int limit) {
        return histories.findByTradeIdOrderById(tradeId, PageRequest.of(0, limit))
                .stream().map(TradeHistoryRow::toHistory).toList();
    }

    public Instant databaseNow() {
        return jdbc.sql("SELECT clock_timestamp()").query(OffsetDateTime.class).single().toInstant();
    }

    public boolean pendingDuplicate(long productId, long buyerId, long excluding) {
        return jdbc.sql("""
                SELECT EXISTS (SELECT 1 FROM trade WHERE product_id = :product AND buyer_id = :buyer
                    AND status = 'pending_acceptance' AND id <> :excluding)
                """).param("product", productId).param("buyer", buyerId).param("excluding", excluding)
                .query(Boolean.class).single();
    }

    private Trade trade(ResultSet row) throws SQLException {
        return new Trade(row.getLong("id"), row.getLong("product_id"), row.getLong("buyer_id"),
                row.getLong("seller_id"), TradeStatus.from(row.getString("status")), row.getString("request_note"),
                row.getObject("active_agreement_id", Long.class), row.getInt("version"),
                row.getString("close_reason"), row.getString("terminal_reason"), instant(row, "requested_at"),
                instant(row, "responded_at"), instant(row, "ended_at"), instant(row, "created_at"),
                instant(row, "updated_at"));
    }

    private TradeModels.Agreement agreementRow(ResultSet row) throws SQLException {
        return new TradeModels.Agreement(row.getLong("id"), row.getLong("trade_id"),
                row.getObject("base_agreement_id", Long.class), row.getInt("version_no"),
                TradeVocabulary.AgreementStatus.from(row.getString("status")), row.getLong("proposed_by"),
                instant(row, "delivery_at"), row.getString("delivery_place_text"), row.getString("delivery_method"),
                row.getLong("amount_cents"), row.getString("payment_method"), row.getString("payment_timing"),
                instant(row, "proposed_at"), row.getObject("business_event_id", UUID.class));
    }

    private TradeModels.Cancellation cancellationRow(ResultSet row) throws SQLException {
        return new TradeModels.Cancellation(row.getLong("id"), row.getLong("trade_id"), row.getLong("proposed_by"),
                TradeVocabulary.CancellationMode.from(row.getString("mode")), row.getString("reason"),
                TradeVocabulary.CancellationStatus.from(row.getString("status")), instant(row, "proposed_at"),
                row.getObject("business_event_id", UUID.class));
    }

    private TradeModels.Dispute disputeRow(ResultSet row) throws SQLException {
        return new TradeModels.Dispute(row.getLong("id"), row.getLong("trade_id"), row.getLong("initiator_id"),
                row.getString("statement"), TradeVocabulary.DisputeStatus.from(row.getString("status")),
                enumValue(row, "resolution_mode", TradeVocabulary.ResolutionMode::from),
                row.getObject("resolved_by", Long.class), row.getObject("case_id", Long.class),
                instant(row, "opened_at"), instant(row, "resolved_at"));
    }

    private TradeModels.Confirmation confirmationRow(ResultSet row) throws SQLException {
        return new TradeModels.Confirmation(row.getLong("id"), row.getLong("trade_id"), row.getLong("agreement_id"),
                row.getLong("confirmer_id"), row.getString("note"), instant(row, "submitted_at"),
                instant(row, "invalidated_at"),
                enumValue(row, "invalidation_reason", TradeVocabulary.InvalidationReason::from),
                row.getObject("business_event_id", UUID.class));
    }

    private TradeModels.Freeze freezeRow(ResultSet row) throws SQLException {
        return new TradeModels.Freeze(row.getLong("id"), row.getLong("trade_id"),
                TradeVocabulary.FreezeSource.from(row.getString("source")), row.getObject("source_ref", Long.class),
                row.getString("reason"), instant(row, "started_at"), instant(row, "ended_at"),
                row.getObject("ended_by", Long.class));
    }

    private static <T> T enumValue(ResultSet row, String column, java.util.function.Function<String, T> mapper)
            throws SQLException {
        String value = row.getString(column);
        return value == null ? null : mapper.apply(value);
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        var value = row.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.toInstant();
    }

    private static OffsetDateTime time(Instant instant) {
        return instant == null ? null : instant.atOffset(ZoneOffset.UTC);
    }

    private static List<String> stringArray(ResultSet row, String column) throws SQLException {
        var array = row.getArray(column);
        if (array == null) {
            return List.of();
        }
        var values = (Object[]) array.getArray();
        var result = new ArrayList<String>(values.length);
        for (Object value : values) {
            result.add((String) value);
        }
        return result;
    }

    private static List<Long> longArray(ResultSet row, String column) throws SQLException {
        var array = row.getArray(column);
        if (array == null) {
            return List.of();
        }
        var values = (Object[]) array.getArray();
        var result = new ArrayList<Long>(values.length);
        for (Object value : values) {
            result.add(((Number) value).longValue());
        }
        return result;
    }

    private static String textArray(List<String> values) {
        return "{" + values.stream().map(TradeRepository::arrayElement)
                .reduce((left, right) -> left + "," + right).orElse("") + "}";
    }

    private static String longArrayLiteral(List<Long> values) {
        return "{" + values.stream().map(String::valueOf)
                .reduce((left, right) -> left + "," + right).orElse("") + "}";
    }

    private static String arrayElement(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }
}
