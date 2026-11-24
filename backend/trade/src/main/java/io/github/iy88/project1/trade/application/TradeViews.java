package io.github.iy88.project1.trade.application;

import io.github.iy88.project1.trade.domain.Trade;
import io.github.iy88.project1.trade.domain.TradeModels;
import io.github.iy88.project1.trade.domain.TradeStatus;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/** Explicit snake_case HTTP projection; no persistence record is serialised directly. */
final class TradeViews {
    private final JsonMapper json;

    TradeViews(JsonMapper json) {
        this.json = json;
    }

    ObjectNode view(Trade trade, TradeModels.Snapshot snapshot, TradePorts.ProductSummary product,
                    TradeModels.Agreement current, TradeModels.Agreement pending,
                    List<TradeModels.Confirmation> confirmations, TradeModels.Wait wait,
                    List<TradeModels.Freeze> freezes, TradeModels.Cancellation cancellation,
                    TradeModels.Dispute dispute, Long conversationId, Map<Long, TradePorts.AccountProfile> profiles,
                    long viewer, boolean canWrite, Instant now) {
        var node = json.createObjectNode();
        node.put("id", Long.toString(trade.id()));
        node.set("product", product(trade, snapshot, product));
        node.set("buyer", account(trade.buyerId(), profiles));
        node.set("seller", account(trade.sellerId(), profiles));
        node.put("status", trade.status().value());
        if (trade.phase() == null) {
            node.putNull("phase");
        } else {
            node.put("phase", trade.phase().value());
        }
        if (trade.terminalReason() == null) {
            node.putNull("terminal_reason");
        } else {
            node.put("terminal_reason", trade.terminalReason());
        }
        node.set("request", request(trade));
        node.set("agreement", agreements(current, pending));
        node.set("confirmations", confirmations(confirmations, trade));
        node.set("wait", wait(wait, now));
        node.set("freeze", freezes(freezes));
        node.set("cancellation", cancellation(cancellation));
        node.set("dispute", dispute(dispute));
        if (conversationId == null) {
            node.putNull("trade_conversation_id");
        } else {
            node.put("trade_conversation_id", Long.toString(conversationId));
        }
        node.put("version", trade.version());
        node.set("permissions", permissions(trade, pending != null, cancellation != null, confirmations,
                !freezes.isEmpty() || !canWrite, viewer));
        node.put("created_at", instant(trade.createdAt()));
        node.put("updated_at", instant(trade.updatedAt()));
        return node;
    }

    private ObjectNode product(Trade trade, TradeModels.Snapshot snapshot, TradePorts.ProductSummary product) {
        var node = json.createObjectNode();
        node.put("id", Long.toString(trade.productId()));
        if (snapshot != null) {
            node.put("title", snapshot.title());
            node.put("price_cents", snapshot.priceCents());
        } else if (product != null) {
            node.put("title", product.title());
            node.put("price_cents", product.priceCents());
        }
        return node;
    }

    private ObjectNode account(long accountId, Map<Long, TradePorts.AccountProfile> profiles) {
        var node = json.createObjectNode();
        var profile = profiles.get(accountId);
        node.put("id", Long.toString(accountId));
        node.put("display_name", profile == null ? "" : profile.displayName());
        if (profile == null || profile.avatarUrl() == null) {
            node.putNull("avatar_url");
        } else {
            node.put("avatar_url", profile.avatarUrl());
        }
        return node;
    }

    private ObjectNode request(Trade trade) {
        var node = json.createObjectNode();
        node.put("note", trade.requestNote());
        node.put("requested_at", instant(trade.requestedAt()));
        if (trade.respondedAt() == null) {
            node.putNull("responded_at");
        } else {
            node.put("responded_at", instant(trade.respondedAt()));
        }
        node.put("close_reason", trade.closeReason());
        return node;
    }

    private ObjectNode agreements(TradeModels.Agreement current, TradeModels.Agreement pending) {
        var node = json.createObjectNode();
        node.set("current", current == null ? json.nullNode() : agreementItem(current));
        node.set("pending", pending == null ? json.nullNode() : agreementItem(pending));
        return node;
    }

    ObjectNode agreementItem(TradeModels.Agreement agreement) {
        var node = json.createObjectNode();
        node.put("id", Long.toString(agreement.id()));
        if (agreement.baseAgreementId() == null) {
            node.putNull("base_agreement_id");
        } else {
            node.put("base_agreement_id", Long.toString(agreement.baseAgreementId()));
        }
        node.put("version_no", agreement.versionNo());
        node.put("status", agreement.status().value());
        node.put("proposed_by", Long.toString(agreement.proposedBy()));
        node.put("delivery_at", instant(agreement.deliveryAt()));
        node.put("delivery_place_text", agreement.deliveryPlaceText());
        node.put("delivery_method", agreement.deliveryMethod());
        node.put("amount_cents", agreement.amountCents());
        node.put("payment_method", agreement.paymentMethod());
        node.put("payment_timing", agreement.paymentTiming());
        node.put("proposed_at", instant(agreement.proposedAt()));
        return node;
    }

    private ObjectNode confirmations(List<TradeModels.Confirmation> confirmations, Trade trade) {
        var node = json.createObjectNode();
        var items = json.createArrayNode();
        confirmations.forEach(confirmation -> {
            var item = json.createObjectNode();
            item.put("id", Long.toString(confirmation.id()));
            item.put("confirmer_id", Long.toString(confirmation.confirmerId()));
            item.put("agreement_id", Long.toString(confirmation.agreementId()));
            item.put("note", confirmation.note());
            item.put("submitted_at", instant(confirmation.submittedAt()));
            items.add(item);
        });
        node.set("current", items);
        node.put("both_current", hasBoth(confirmations, trade));
        return node;
    }

    private static boolean hasBoth(List<TradeModels.Confirmation> confirmations, Trade trade) {
        return confirmations.stream().anyMatch(item -> item.confirmerId() == trade.buyerId())
                && confirmations.stream().anyMatch(item -> item.confirmerId() == trade.sellerId());
    }

    private ObjectNode wait(TradeModels.Wait wait, Instant now) {
        var node = json.createObjectNode();
        if (wait == null) {
            node.put("active", false);
            node.putNull("started_at");
            node.putNull("deadline_at");
            node.put("remaining_seconds", 0);
            node.put("paused", false);
            return node;
        }
        node.put("active", wait.active());
        node.put("started_at", instant(wait.startedAt()));
        node.put("deadline_at", wait.ended() ? null : instant(wait.deadline(now)));
        node.put("remaining_seconds", wait.ended() ? 0 : wait.remainingSeconds(now));
        node.put("paused", wait.paused());
        if (wait.endedAt() != null) {
            node.put("ended_at", instant(wait.endedAt()));
            node.put("end_reason", wait.endReason().value());
        }
        return node;
    }

    private ObjectNode freezes(List<TradeModels.Freeze> freezes) {
        var node = json.createObjectNode();
        node.put("active", !freezes.isEmpty());
        var items = json.createArrayNode();
        freezes.forEach(freeze -> {
            var item = json.createObjectNode();
            item.put("id", Long.toString(freeze.id()));
            item.put("source", freeze.source().value());
            if (freeze.sourceRef() == null) {
                item.putNull("source_ref");
            } else {
                item.put("source_ref", Long.toString(freeze.sourceRef()));
            }
            item.put("reason", freeze.reason());
            item.put("started_at", instant(freeze.startedAt()));
            items.add(item);
        });
        node.set("items", items);
        return node;
    }

    private ObjectNode cancellation(TradeModels.Cancellation cancellation) {
        var node = json.createObjectNode();
        if (cancellation == null) {
            node.putNull("pending");
            return node;
        }
        var pending = json.createObjectNode();
        pending.put("id", Long.toString(cancellation.id()));
        pending.put("proposed_by", Long.toString(cancellation.proposedBy()));
        pending.put("mode", cancellation.mode().value());
        pending.put("reason", cancellation.reason());
        pending.put("proposed_at", instant(cancellation.proposedAt()));
        node.set("pending", pending);
        return node;
    }

    private ObjectNode dispute(TradeModels.Dispute dispute) {
        var node = json.createObjectNode();
        if (dispute == null) {
            node.putNull("open");
            return node;
        }
        var open = json.createObjectNode();
        open.put("id", Long.toString(dispute.id()));
        open.put("initiator_id", Long.toString(dispute.initiatorId()));
        open.put("statement", dispute.statement());
        open.put("opened_at", instant(dispute.openedAt()));
        node.set("open", open);
        return node;
    }

    private ObjectNode permissions(Trade trade, boolean pendingAgreement, boolean pendingCancellation,
                                   List<TradeModels.Confirmation> confirmations, boolean frozen, long viewer) {
        var node = json.createObjectNode();
        boolean ownConfirmation = confirmations.stream().anyMatch(item -> item.confirmerId() == viewer);
        var actions = json.createArrayNode();
        trade.allowedActions(viewer, pendingAgreement, pendingCancellation, ownConfirmation, frozen)
                .forEach(actions::add);
        node.set("allowed_actions", actions);
        return node;
    }

    ObjectNode confirmationRecord(TradeModels.Confirmation confirmation) {
        var item = json.createObjectNode();
        item.put("id", Long.toString(confirmation.id()));
        item.put("agreement_id", Long.toString(confirmation.agreementId()));
        item.put("confirmer_id", Long.toString(confirmation.confirmerId()));
        item.put("note", confirmation.note());
        item.put("submitted_at", instant(confirmation.submittedAt()));
        item.putNull("invalidated_at");
        return item;
    }

    ObjectNode cancellationRecord(TradeModels.Cancellation cancellation) {
        var item = json.createObjectNode();
        item.put("id", Long.toString(cancellation.id()));
        item.put("proposed_by", Long.toString(cancellation.proposedBy()));
        item.put("mode", cancellation.mode().value());
        item.put("reason", cancellation.reason());
        item.put("status", cancellation.status().value());
        item.put("proposed_at", instant(cancellation.proposedAt()));
        return item;
    }

    ObjectNode disputeRecord(TradeModels.Dispute dispute) {
        var item = json.createObjectNode();
        item.put("id", Long.toString(dispute.id()));
        item.put("initiator_id", Long.toString(dispute.initiatorId()));
        item.put("statement", dispute.statement());
        item.put("status", dispute.status().value());
        item.put("opened_at", instant(dispute.openedAt()));
        if (dispute.resolvedAt() == null) {
            item.putNull("resolved_at");
        } else {
            item.put("resolved_at", instant(dispute.resolvedAt()));
        }
        return item;
    }

    void history(ObjectNode target, List<TradeModels.History> history) {
        var items = json.createArrayNode();
        history.forEach(entry -> {
            var item = json.createObjectNode();
            item.put("id", Long.toString(entry.id()));
            item.put("action", entry.action());
            boolean freezeTransition = entry.freezeId() != null;
            item.put("from_status", freezeTransition ? null : entry.fromStatus());
            item.put("to_status", freezeTransition ? null : entry.toStatus());
            item.put("from_phase", freezeTransition ? null : entry.fromPhase());
            item.put("to_phase", freezeTransition ? null : entry.toPhase());
            item.put("actor_kind", entry.actorKind().value());
            if (entry.actorId() == null || entry.actorKind() == TradeVocabulary.ActorKind.ADMIN
                    || entry.actorKind() == TradeVocabulary.ActorKind.SYSTEM) {
                item.putNull("actor_id");
            } else {
                item.put("actor_id", Long.toString(entry.actorId()));
            }
            item.put("reason", entry.reason());
            item.put("basis_ref", entry.basisRef());
            if (entry.caseId() == null) {
                item.putNull("case_id");
            } else {
                item.put("case_id", Long.toString(entry.caseId()));
            }
            item.put("business_event_id", entry.businessEventId().toString());
            item.put("created_at", instant(entry.createdAt()));
            items.add(item);
        });
        target.set("state_history", items);
    }

    void agreements(ObjectNode target, List<TradeModels.Agreement> agreements) {
        var items = json.createArrayNode();
        agreements.forEach(agreement -> items.add(agreementItem(agreement)));
        target.set("agreement_history", items);
    }

    void confirmations(ObjectNode target, List<TradeModels.Confirmation> confirmations) {
        var items = json.createArrayNode();
        confirmations.forEach(confirmation -> {
            var item = json.createObjectNode();
            item.put("id", Long.toString(confirmation.id()));
            item.put("agreement_id", Long.toString(confirmation.agreementId()));
            item.put("confirmer_id", Long.toString(confirmation.confirmerId()));
            item.put("note", confirmation.note());
            item.put("submitted_at", instant(confirmation.submittedAt()));
            if (confirmation.invalidatedAt() == null) {
                item.putNull("invalidated_at");
                item.putNull("invalidation_reason");
            } else {
                item.put("invalidated_at", instant(confirmation.invalidatedAt()));
                item.put("invalidation_reason", confirmation.invalidationReason().value());
            }
            items.add(item);
        });
        target.set("confirmation_history", items);
    }

    static String instant(Instant instant) {
        return instant == null ? null : instant.toString();
    }
}
