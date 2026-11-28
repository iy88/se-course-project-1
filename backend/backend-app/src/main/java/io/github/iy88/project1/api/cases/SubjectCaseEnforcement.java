package io.github.iy88.project1.api.cases;

import io.github.iy88.project1.account.application.AccountRestrictions;
import io.github.iy88.project1.casemanagement.application.CasePorts;
import io.github.iy88.project1.casemanagement.application.CaseRecords;
import io.github.iy88.project1.casemanagement.application.SubjectPlan;
import io.github.iy88.project1.casemanagement.persistence.CaseLifecycleStore;
import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.product.application.ProductDisplayRestrictions;
import io.github.iy88.project1.product.application.ProductInteractions;
import io.github.iy88.project1.product.persistence.Product;
import io.github.iy88.project1.product.persistence.ProductRepository;
import io.github.iy88.project1.trade.application.TradePorts;
import io.github.iy88.project1.trade.domain.TradeVocabulary;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;

/**
 * Account and product subject execution for one decided case batch.
 *
 * <p>The case application locks the CASE row and every subject row through a merged
 * {@link SubjectPlan} before calling this handler. This class never takes an account advisory lock
 * or widens the resource plan itself: a candidate that appeared after planning is reported as
 * {@link LockPlan.Changed} so the shared write executor rolls back and re-plans the whole batch.</p>
 */
final class SubjectCaseEnforcement {
    private static final Set<String> SUPPORTED = Set.of(
            "restrict_account", "lift_account_restriction", "withdraw_public_access", "restore_display");

    private final CaseLifecycleStore cases;
    private final CasePorts.Targets targets;
    private final AccountRestrictions accounts;
    private final ProductDisplayRestrictions displays;
    private final ProductRepository products;
    private final ProductInteractions interactions;
    private final TradePorts.Closure closures;
    private final TradePorts.CaseEnforcement trades;
    private final TradePorts.Participation participation;
    private final Clock clock;

    SubjectCaseEnforcement(CaseLifecycleStore cases, CasePorts.Targets targets, AccountRestrictions accounts,
                           ProductDisplayRestrictions displays, ProductRepository products,
                           ProductInteractions interactions, TradePorts.Closure closures,
                           TradePorts.CaseEnforcement trades, TradePorts.Participation participation, Clock clock) {
        this.cases = Objects.requireNonNull(cases);
        this.targets = Objects.requireNonNull(targets);
        this.accounts = Objects.requireNonNull(accounts);
        this.displays = Objects.requireNonNull(displays);
        this.products = Objects.requireNonNull(products);
        this.interactions = Objects.requireNonNull(interactions);
        this.closures = Objects.requireNonNull(closures);
        this.trades = Objects.requireNonNull(trades);
        this.participation = Objects.requireNonNull(participation);
        this.clock = clock == null ? Clock.systemUTC() : clock;
    }

    boolean supports(String action) {
        return SUPPORTED.contains(action);
    }

    // ------------------------------------------------------------------ read-only plans

    LockPlan plan(long caseId, List<CaseRecords.EnforcementInstruction> items) {
        return lockCallbacks(caseId, items).lockPlan();
    }

    SubjectPlan lockCallbacks(long caseId, List<CaseRecords.EnforcementInstruction> items) {
        var subjects = SubjectPlan.empty();
        for (var item : items) {
            requireSupported(item);
            subjects = subjects.merge(switch (item.action()) {
                case "restrict_account" -> accountBanCallbacks(item.targetId());
                case "withdraw_public_access" -> productCallbacks(item.targetId())
                        .merge(closureCallbacks(closures.productClosurePlan(item.targetId())));
                case "lift_account_restriction" -> accountLiftCallbacks(caseId, item.targetId());
                case "restore_display" -> productCallbacks(item.targetId());
                default -> throw unsupported();
            });
        }
        return subjects;
    }

    private SubjectPlan accountBanCallbacks(long accountId) {
        var subjects = SubjectPlan.account(accountId, LockPlan.AccountMode.EXCLUSIVE);
        for (long productId : displays.sellerProductIds(accountId)) {
            subjects = subjects.merge(productCallbacks(productId));
        }
        return subjects.merge(closureCallbacks(closures.accountBanPlan(accountId)));
    }

    private SubjectPlan accountLiftCallbacks(long caseId, long accountId) {
        var subjects = SubjectPlan.account(accountId, LockPlan.AccountMode.EXCLUSIVE);
        var active = accounts.findActive(accountId, caseId, now());
        if (active.isPresent()) {
            for (long productId : displays.productIdsForSource(
                    ProductDisplayRestrictions.ACCOUNT_BAN, active.get().id())) {
                subjects = subjects.merge(productCallbacks(productId));
            }
        }
        return subjects.merge(closureCallbacks(closures.accountBanPlan(accountId)));
    }

    private SubjectPlan productCallbacks(long productId) {
        return SubjectPlan.resource(productKey(productId),
                transaction -> trades.lockCaseProductRow(transaction, productId));
    }

    /**
     * Maps the trade-owned closure plan onto row-only callbacks. The product rows are added by the
     * caller; closure plans only carry accounts and trade/conversation rows.
     */
    private SubjectPlan closureCallbacks(LockPlan plan) {
        var subjects = SubjectPlan.empty();
        for (var entry : plan.accounts().entrySet()) {
            subjects = subjects.merge(SubjectPlan.account(entry.getKey(), entry.getValue()));
        }
        for (var key : plan.resources()) {
            long id = key.parts().get(0);
            subjects = subjects.merge(SubjectPlan.resource(key, switch (key.domain()) {
                case PRODUCT -> transaction -> trades.lockCaseProductRow(transaction, id);
                case TRADE -> transaction -> trades.lockTradeRow(transaction, id);
                case TRADE_CONVERSATION -> transaction -> trades.lockConversationRow(transaction, id);
                default -> throw new IllegalStateException("Unsupported closure lock domain " + key.domain());
            }));
        }
        return subjects;
    }

    // ------------------------------------------------------------------ apply

    List<CaseRecords.EnforcementOutcome> execute(WriteTransaction transaction, long caseId, String reason,
                                                 String basisRef,
                                                 List<CaseRecords.EnforcementInstruction> items,
                                                 Instant occurredAt) {
        var facts = cases.requireLocked(transaction, caseId);
        var outcomes = new ArrayList<CaseRecords.EnforcementOutcome>();
        for (var item : items) {
            requireSupported(item);
            outcomes.add(switch (item.action()) {
                case "restrict_account" -> restrictAccount(transaction, facts, item, reason, basisRef, occurredAt);
                case "withdraw_public_access" -> withdraw(transaction, facts, item, reason, basisRef, occurredAt);
                case "lift_account_restriction" -> liftAccount(transaction, facts, item, reason, basisRef, occurredAt);
                case "restore_display" -> restoreDisplay(transaction, facts, item, reason, basisRef, occurredAt);
                default -> throw unsupported();
            });
        }
        return outcomes;
    }

    private CaseRecords.EnforcementOutcome restrictAccount(WriteTransaction transaction, CaseRecords.Facts facts,
                                                           CaseRecords.EnforcementInstruction item, String reason,
                                                           String basisRef, Instant occurredAt) {
        long accountId = item.targetId();
        requireTargetAccount(facts, accountId);
        var ban = accounts.apply(transaction, accountId, facts.caseId(), reason, basisRef, occurredAt);
        int changed = ban.alreadyEffective() ? 0 : 1;
        for (long productId : displays.sellerProductIds(accountId)) {
            requireProductLocked(transaction, productId);
            var applied = displays.applyLocked(transaction, productId, ProductDisplayRestrictions.ACCOUNT_BAN,
                    ban.id(), reason, basisRef, occurredAt);
            if (!applied.alreadyActive()) {
                changed++;
            }
        }
        changed += closures.applyAccountBanLocked(transaction, accountId, ban.id(), reason, basisRef);
        boolean replayed = changed == 0;
        return new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(), "account", accountId,
                "account_restriction", ban.id(), replayed ? "replayed" : "applied",
                "write=" + (ban.alreadyEffective() ? "restricted" : "active"), "write=restricted",
                replayed ? List.of() : List.of(accountId), occurredAt, List.of());
    }

    private CaseRecords.EnforcementOutcome withdraw(WriteTransaction transaction, CaseRecords.Facts facts,
                                                    CaseRecords.EnforcementInstruction item, String reason,
                                                    String basisRef, Instant occurredAt) {
        long productId = item.targetId();
        Product product = requireWithdrawableProduct(facts, productId);
        requireProductLocked(transaction, productId);
        var applied = displays.applyLocked(transaction, productId, ProductDisplayRestrictions.ADMIN_CASE,
                facts.caseId(), reason, basisRef, occurredAt);
        int closed = closures.closePendingForProductLocked(transaction, productId,
                TradeVocabulary.CloseReason.PUBLIC_ACCESS_REVOKED, basisRef);
        boolean replayed = applied.alreadyActive() && closed == 0;
        return new CaseRecords.EnforcementOutcome(item.enforcementId(), item.action(), "product", productId,
                "product_display_restriction", applied.restrictionId(), replayed ? "replayed" : "applied",
                "display=" + (applied.alreadyActive() ? "restricted" : "visible"), "display=restricted",
                replayed ? List.of() : List.of(product.sellerAccountId()), occurredAt, List.of());
    }

    private CaseRecords.EnforcementOutcome liftAccount(WriteTransaction transaction, CaseRecords.Facts facts,
                                                       CaseRecords.EnforcementInstruction item, String reason,
                                                       String basisRef, Instant occurredAt) {
        long accountId = item.targetId();
        requireTargetAccount(facts, accountId);
        var ban = accounts.findActive(accountId, facts.caseId(), occurredAt)
                .orElseThrow(SubjectCaseEnforcement::restrictionNotActive);
        return releaseAccount(transaction, facts, accountId, ban.id(), item.enforcementId(), reason, basisRef,
                occurredAt);
    }

    private CaseRecords.EnforcementOutcome restoreDisplay(WriteTransaction transaction, CaseRecords.Facts facts,
                                                          CaseRecords.EnforcementInstruction item, String reason,
                                                          String basisRef, Instant occurredAt) {
        long productId = item.targetId();
        Product product = requireWithdrawableProduct(facts, productId);
        var restriction = displays.findActive(productId, ProductDisplayRestrictions.ADMIN_CASE, facts.caseId())
                .orElseThrow(SubjectCaseEnforcement::restrictionNotActive);
        return releaseProduct(transaction, product, restriction.restrictionId(), item.enforcementId(),
                reason, basisRef, occurredAt);
    }

    // ------------------------------------------------------------------ reverse

    List<CaseRecords.EnforcementOutcome> reverse(WriteTransaction transaction, long caseId,
                                                 CaseRecords.Enforcement recorded, String basisRef,
                                                 String reason, Instant occurredAt) {
        if ("restrict_account".equals(recorded.action()) && "account".equals(recorded.targetType())) {
            long banId = requireResultId(recorded, "account_restriction");
            var ban = accounts.find(banId).orElseThrow(SubjectCaseEnforcement::restrictionNotActive);
            if (ban.accountId() != recorded.targetId() || ban.caseId() != caseId) {
                throw ownershipMismatch();
            }
            var facts = cases.requireLocked(transaction, caseId);
            requireTargetAccount(facts, recorded.targetId());
            return List.of(releaseAccount(transaction, facts, recorded.targetId(), banId, liftId(recorded),
                    reason, basisRef, occurredAt));
        }
        if ("withdraw_public_access".equals(recorded.action()) && "product".equals(recorded.targetType())) {
            long restrictionId = requireResultId(recorded, "product_display_restriction");
            var restriction = displays.find(restrictionId).orElseThrow(SubjectCaseEnforcement::restrictionNotActive);
            if (restriction.productId() != recorded.targetId()
                    || !ProductDisplayRestrictions.ADMIN_CASE.equals(restriction.sourceType())
                    || restriction.sourceRefId() != caseId) {
                throw ownershipMismatch();
            }
            var facts = cases.requireLocked(transaction, caseId);
            Product product = requireWithdrawableProduct(facts, recorded.targetId());
            return List.of(releaseProduct(transaction, product, restrictionId, liftId(recorded), reason,
                    basisRef, occurredAt));
        }
        throw new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该处置动作的反向执行尚未启用");
    }

    LockPlan reversePlan(long caseId, CaseRecords.Enforcement recorded) {
        return reverseLockCallbacks(caseId, recorded).lockPlan();
    }

    SubjectPlan reverseLockCallbacks(long caseId, CaseRecords.Enforcement recorded) {
        if ("restrict_account".equals(recorded.action()) && "account".equals(recorded.targetType())) {
            long banId = requireResultId(recorded, "account_restriction");
            var subjects = SubjectPlan.account(recorded.targetId(), LockPlan.AccountMode.EXCLUSIVE);
            for (long productId : displays.productIdsForSource(ProductDisplayRestrictions.ACCOUNT_BAN, banId)) {
                subjects = subjects.merge(productCallbacks(productId));
            }
            return subjects.merge(closureCallbacks(closures.accountBanPlan(recorded.targetId())));
        }
        if ("withdraw_public_access".equals(recorded.action()) && "product".equals(recorded.targetType())) {
            requireResultId(recorded, "product_display_restriction");
            return productCallbacks(recorded.targetId());
        }
        return SubjectPlan.empty();
    }

    // ------------------------------------------------------------------ shared mutations

    /**
     * Releases only the account row, display rows and trade freezes sourced by this one ban. The
     * caller has already validated the recorded result reference; no client-supplied restriction
     * identity reaches these writes.
     */
    private CaseRecords.EnforcementOutcome releaseAccount(WriteTransaction transaction, CaseRecords.Facts facts,
                                                          long accountId, long banId, String enforcementId,
                                                          String reason, String basisRef, Instant occurredAt) {
        accounts.release(transaction, accountId, facts.caseId(), banId, reason, basisRef, occurredAt);
        for (long productId : displays.productIdsForSource(ProductDisplayRestrictions.ACCOUNT_BAN, banId)) {
            requireProductLocked(transaction, productId);
            displays.releaseLocked(transaction, productId, ProductDisplayRestrictions.ACCOUNT_BAN, banId,
                    reason, basisRef, occurredAt);
        }
        closures.removeAccountBanLocked(transaction, accountId, banId, basisRef);
        List<String> remaining = remainingAccountRestrictions(accountId, banId, occurredAt);
        return new CaseRecords.EnforcementOutcome(enforcementId, "lift_account_restriction", "account", accountId,
                "account_restriction", banId, "applied", "write=restricted",
                "write=" + (remaining.contains("account_restriction") ? "restricted" : "active"),
                List.of(accountId), occurredAt, remaining);
    }

    private CaseRecords.EnforcementOutcome releaseProduct(WriteTransaction transaction, Product product,
                                                          long restrictionId, String enforcementId, String reason,
                                                          String basisRef, Instant occurredAt) {
        requireProductLocked(transaction, product.id());
        var released = displays.releaseLocked(transaction, product.id(), restrictionId, reason, basisRef,
                occurredAt);
        boolean stillRestricted = displays.hasActive(product.id());
        var remaining = stillRestricted ? List.of("product_display_restriction") : List.<String>of();
        boolean replayed = released.alreadyReleased();
        return new CaseRecords.EnforcementOutcome(enforcementId, "restore_display", "product", product.id(),
                "product_display_restriction", restrictionId, replayed ? "replayed" : "applied",
                "display=restricted", "display=" + (stillRestricted ? "restricted" : "visible"),
                replayed ? List.of() : List.of(product.sellerAccountId()), occurredAt, remaining);
    }

    private List<String> remainingAccountRestrictions(long accountId, long banId, Instant at) {
        var remaining = new TreeSet<String>();
        if (accounts.isRestricted(accountId, at)) {
            remaining.add("account_restriction");
        }
        for (long productId : displays.productIdsForSource(ProductDisplayRestrictions.ACCOUNT_BAN, banId)) {
            if (displays.hasActive(productId)) {
                remaining.add("product_display_restriction");
                break;
            }
        }
        if (closures.hasActiveAccountFreeze(accountId)) {
            remaining.add("trade_freeze");
        }
        return List.copyOf(remaining);
    }

    // ------------------------------------------------------------------ validation

    private void requireTargetAccount(CaseRecords.Facts facts, long accountId) {
        if (facts.reporterAccountId() != null && facts.reporterAccountId() == accountId) {
            throw ownershipMismatch();
        }
        if (!targets.relatedAccountIds(facts).contains(accountId)) {
            throw ownershipMismatch();
        }
    }

    /**
     * A withdrawal target must be the case's direct product, the product carrying a reported
     * comment or trade, or a product of the directly reported account. Anything else is rejected
     * rather than inferred from conversation participation.
     */
    private Product requireWithdrawableProduct(CaseRecords.Facts facts, long productId) {
        Product product = products.findById(productId)
                .filter(found -> !found.deleted())
                .orElseThrow(() -> new BusinessError("RESOURCE_NOT_VISIBLE", 404, "商品不存在"));
        boolean related = switch (facts.targetType() == null ? "" : facts.targetType()) {
            case "product" -> facts.targetId() != null && facts.targetId() == productId;
            case "comment" -> facts.targetId() != null
                    && interactions.commentProductId(facts.targetId()).orElse(-1) == productId;
            case "trade" -> facts.targetId() != null
                    && participation.productId(facts.targetId()).orElse(-1) == productId;
            case "account" -> facts.targetId() != null && product.sellerAccountId() == facts.targetId();
            default -> false;
        };
        if (!related) {
            throw ownershipMismatch();
        }
        return product;
    }

    private static void requireProductLocked(WriteTransaction transaction, long productId) {
        var key = productKey(productId);
        if (!transaction.isAcquired(key)) {
            throw new LockPlan.Changed(new LockPlan(Map.of(), Set.of(key)));
        }
    }

    private static long requireResultId(CaseRecords.Enforcement recorded, String resultType) {
        if (!resultType.equals(recorded.resultType()) || recorded.resultId() == null || recorded.resultId() <= 0) {
            throw restrictionNotActive();
        }
        return recorded.resultId();
    }

    private static String liftId(CaseRecords.Enforcement recorded) {
        return recorded.enforcementId() + "-lift";
    }

    private Instant now() {
        return clock.instant().truncatedTo(ChronoUnit.MICROS);
    }

    private static LockPlan.Key productKey(long productId) {
        return new LockPlan.Key(LockPlan.Domain.PRODUCT, List.of(productId));
    }

    private static void requireSupported(CaseRecords.EnforcementInstruction item) {
        if (!SUPPORTED.contains(item.action())) {
            throw unsupported();
        }
        boolean accountAction = "restrict_account".equals(item.action())
                || "lift_account_restriction".equals(item.action());
        boolean productAction = "withdraw_public_access".equals(item.action())
                || "restore_display".equals(item.action());
        if ((accountAction && !"account".equals(item.targetType()))
                || (productAction && !"product".equals(item.targetType()))) {
            throw new BusinessError("TARGET_INVALID", 422, "执行目标与动作不匹配");
        }
    }

    private static BusinessError unsupported() {
        return new BusinessError("DEPENDENCY_UNAVAILABLE", 503, "该处置动作的正式执行由 S4-01 提供");
    }

    private static BusinessError restrictionNotActive() {
        return new BusinessError("RESTRICTION_NOT_ACTIVE", 409, "原限制记录不存在或已解除");
    }

    private static BusinessError ownershipMismatch() {
        return new BusinessError("OWNERSHIP_MISMATCH", 403, "目标不属于本事项的实际关联主体");
    }
}
