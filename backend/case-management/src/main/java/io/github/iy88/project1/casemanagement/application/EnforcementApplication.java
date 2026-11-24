package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.BusinessError;
import io.github.iy88.project1.core.ExecutionContext;
import io.github.iy88.project1.core.LockPlan;
import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteExecutor;
import io.github.iy88.project1.core.WriteResult;
import io.github.iy88.project1.core.WriteTransaction;
import io.github.iy88.project1.storage.FilePurpose;
import io.github.iy88.project1.storage.persistence.FileReferences;
import io.github.iy88.project1.storage.persistence.FileRegistry;
import io.github.iy88.project1.storage.persistence.UploadRegistration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import java.util.function.Function;
import java.util.stream.Collectors;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Application orchestration for one decision execution.
 *
 * <p>The application discovers the union of subject locks from read-only preparations, acquires
 * every row once in the global {@link LockPlan.Key} order under one S1 write transaction, then
 * revalidates the case and applies the named subject capabilities. It does not own account,
 * product, trade, conversation or case state; those remain behind the ports supplied by their
 * modules.</p>
 */
public final class EnforcementApplication implements WriteExecutor.UseCase<EnforcementCommand, CaseAccess> {
    public static final String OPERATION = "case.enforcement.batch";
    /** Only genuine subject business failures are eligible for the case-owned failure trail. */
    private static final Set<String> FAILURE_TRAIL_CODES = Set.of(
            "TARGET_STATE_CONFLICT", "TRADE_TERMINAL", "TRANSITION_NOT_ALLOWED",
            "RESTRICTION_NOT_ACTIVE", "TRADE_FREEZE_NOT_ACTIVE", "CONTENT_NOT_FOUND");

    private final WriteExecutor writes;
    private final CaseEnforcementPort cases;
    private final AccountEnforcementPort accounts;
    private final ProductEnforcementPort products;
    private final TradeEnforcementPort trades;
    private final ConversationEnforcementPort conversations;
    private final EnforcementNotifications notifications;
    private final FileReferences files;
    private final JsonMapper json;

    public EnforcementApplication(WriteExecutor writes, CaseEnforcementPort cases,
                                  AccountEnforcementPort accounts, ProductEnforcementPort products,
                                  TradeEnforcementPort trades, ConversationEnforcementPort conversations,
                                  EnforcementNotifications notifications, FileReferences files, JsonMapper json) {
        this.writes = Objects.requireNonNull(writes);
        this.cases = Objects.requireNonNull(cases);
        this.accounts = Objects.requireNonNull(accounts);
        this.products = Objects.requireNonNull(products);
        this.trades = Objects.requireNonNull(trades);
        this.conversations = Objects.requireNonNull(conversations);
        this.notifications = Objects.requireNonNull(notifications);
        this.files = Objects.requireNonNull(files);
        this.json = Objects.requireNonNull(json);
    }

    public WriteResult<JsonNode> execute(ExecutionContext context, String idempotencyKey,
                                         EnforcementCommand command) {
        return writes.run(context, OPERATION, idempotencyKey, command, this);
    }

    @Override
    public JsonNode digestInput(EnforcementCommand request) {
        var root = json.createObjectNode();
        root.put("case_id", request.caseId());
        root.put("reason", request.reason());
        var basis = root.putArray("basis_refs");
        request.basisRefs().forEach(basis::add);
        var evidence = root.putArray("evidence_file_ids");
        request.evidenceFileIds().forEach(evidence::add);
        var items = root.putArray("enforcements");
        for (var instruction : request.enforcements()) {
            var item = items.addObject();
            item.put("enforcement_id", instruction.enforcementId());
            item.put("action", instruction.action().name());
            item.put("target_type", instruction.target().type());
            item.put("target_id", instruction.target().id());
            if (instruction.detail() != null) {
                item.put("detail_type", instruction.detail().type());
                item.put("detail_id", instruction.detail().id());
            }
            if (instruction.expectedResult() != null) {
                item.put("expected_result", instruction.expectedResult());
            }
        }
        return root;
    }

    /**
     * Read-only candidate lock plan for the batch. Transaction owners merge their own
     * {@link SubjectPlan} before returning a {@link LockPlan} from their S1 prepare phase.
     */
    public SubjectPlan preparePlan(ExecutionContext context, EnforcementCommand request) {
        return plan(request, cases.prepare(context, request));
    }

    @Override
    public LockPlan prepare(ExecutionContext context, EnforcementCommand request) {
        return preparePlan(context, request).lockPlan();
    }

    @Override
    public CaseAccess qualify(ExecutionContext context, EnforcementCommand request, LockPlan plan) {
        return cases.requireManager(context, request);
    }

    @Override
    public void requireReplayAccess(ExecutionContext context, CaseAccess qualifications, ResourceRef resource) {
        if (!"case".equals(resource.type())) {
            throw new BusinessError("RESOURCE_NOT_VISIBLE", 404, "事项不可见");
        }
        cases.requireReplayAccess(context, resource.id());
    }

    /**
     * Runs the batch inside the caller's S1 write transaction. The caller's operation
     * owns idempotency and the HTTP response; this method contributes the case/subject locks,
     * the optional post-lock step and the per-action audit/notification side effects.
     *
     * <p>Pass the lock plan received by the caller's write callback as {@code prepared}.
     * {@code additional} is merged into the same de-duplicated plan before locking. The
     * {@code afterLocks} step runs after every planned resource is locked but before the decided
     * case is required, so a decision can be written in the same transaction. It must not call
     * {@code transaction.lock} for the CASE key again; that key is already locked by this batch.
     * The step is skipped when every enforcement ID already has a persisted outcome.</p>
     */
    public EnforcementBatch executeInTransaction(WriteTransaction transaction, EnforcementCommand command,
                                                 LockPlan prepared, SubjectPlan additional, AfterLocks afterLocks) {
        var access = cases.requireManager(transaction.context(), command);
        return executeBatch(transaction, command, access, prepared, additional, afterLocks);
    }

    @Override
    public WriteResult.Response<?> write(WriteTransaction transaction, EnforcementCommand command,
                                         CaseAccess qualifications, LockPlan prepared) {
        var batch = executeBatch(transaction, command, qualifications, prepared, SubjectPlan.empty(), null);
        return new WriteResult.Response<>(201, batch, batch.caseRef());
    }

    private EnforcementBatch executeBatch(WriteTransaction transaction, EnforcementCommand command,
                                          CaseAccess qualifications, LockPlan prepared,
                                          SubjectPlan additional, AfterLocks afterLocks) {
        var context = transaction.context();
        var plan = plan(command, qualifications).merge(additional);
        requirePrepared(plan, prepared);
        plan.acquire(transaction);

        var access = cases.revalidate(transaction, context, command, qualifications);
        var locked = new LockPlan(prepared.accounts(), plan.lockPlan().resources());
        requirePrepared(plan(command, access).merge(additional), locked);

        boolean allPrior = allPrior(command, access);
        if (!allPrior) {
            if (afterLocks != null) {
                afterLocks.run(transaction, access);
                // The caller may have written the decision. Re-read the case facts under the
                // locks before checking the decided basis or deriving any resource plan.
                access = cases.revalidate(transaction, context, command, access);
                requirePrepared(plan(command, access).merge(additional), locked);
            }
            cases.requireExecutable(transaction, context, command, access);
        }

        var references = allPrior ? List.<FileReferences.Reference>of() : attachEvidence(command, access);
        var outcomes = new ArrayList<EnforcementOutcome>();
        var newOutcomes = new ArrayList<EnforcementOutcome>();
        var notified = new TreeSet<Long>();
        var pendingNotifications = new ArrayList<PendingNotification>();
        for (var instruction : command.enforcements()) {
            var prior = access.priorExecutions().get(instruction.enforcementId());
            if (prior != null) {
                if (prior.action() != instruction.action() || !prior.target().equals(instruction.target())) {
                    throw new BusinessError("IDEMPOTENCY_PAYLOAD_CONFLICT", 409, "执行标识已用于其他动作或目标");
                }
                instruction.action().requireResult(instruction.target(), prior.result());
                outcomes.add(prior.replayed());
                continue;
            }
            var result = apply(transaction, command, instruction, access);
            var outcome = outcome(instruction, result, command.occurredAt());
            outcomes.add(outcome);
            newOutcomes.add(outcome);
            if (!result.alreadyEffective()) {
                audit(transaction, access, outcome);
                if (!result.recipientAccountIds().isEmpty()) {
                    notified.addAll(result.recipientAccountIds());
                    pendingNotifications.add(new PendingNotification(outcome, result.recipientAccountIds()));
                }
            }
        }

        if (!newOutcomes.isEmpty()) {
            cases.recordExecution(transaction, context, command, newOutcomes, references);
        }
        for (var pending : pendingNotifications) {
            var outcome = pending.outcome();
            var notification = notification(outcome.action());
            String intentKey = "case:" + command.caseId() + ":" + outcome.enforcementId()
                    + ":" + notification.suffix();
            notifications.create(transaction, notification.eventType(), intentKey, access.caseRef(),
                    pending.recipients(), command.reason(), outcome.occurredAt());
        }
        return new EnforcementBatch(command.caseId(), outcomes, List.copyOf(notified));
    }

    private static void requirePrepared(SubjectPlan plan, LockPlan prepared) {
        var missing = plan.missingFrom(prepared);
        if (!missing.accounts().isEmpty() || !missing.resources().isEmpty()) {
            throw new LockPlan.Changed(missing);
        }
    }

    /** Caller-owned step that runs after all planned resources are locked. */
    @FunctionalInterface
    public interface AfterLocks {
        void run(WriteTransaction transaction, CaseAccess access);
    }

    /**
     * Delegates the case-owned failure trail after the S1 transaction rolled back. Only genuine
     * failed subject execution is recorded. Authorization, idempotency and case-state failures
     * belong to their respective case entry points.
     */
    public void recordFailure(ExecutionContext context, EnforcementCommand command, BusinessError failure) {
        if (!FAILURE_TRAIL_CODES.contains(failure.code())) {
            return;
        }
        cases.recordFailure(context, command, failure.code(), failure.getMessage());
    }

    private SubjectPlan plan(EnforcementCommand command, CaseAccess access) {
        var plan = SubjectPlan.empty().merge(caseLock(command.caseId()));
        for (long accountId : access.partyAccountIds()) {
            plan = plan.merge(SubjectPlan.account(accountId, LockPlan.AccountMode.SHARED));
        }
        boolean allPrior = allPrior(command, access);
        for (var instruction : command.enforcements()) {
            if (access.priorExecutions().containsKey(instruction.enforcementId())) {
                continue;
            }
            var subject = SubjectCommand.of(command, instruction, access);
            plan = plan.merge(accounts.prepare(subject))
                    .merge(products.prepare(subject))
                    .merge(trades.prepare(subject))
                    .merge(conversations.prepare(subject));
        }
        if (!allPrior) {
            plan = plan.merge(evidenceLocks(command, access));
        }
        return plan;
    }

    private SubjectPlan caseLock(long caseId) {
        return SubjectPlan.resource(new LockPlan.Key(LockPlan.Domain.CASE, List.of(caseId)),
                transaction -> cases.lockCase(transaction, caseId));
    }

    private SubjectPlan evidenceLocks(EnforcementCommand command, CaseAccess access) {
        var authorized = access.evidence().stream().map(CaseEvidence::fileId).collect(Collectors.toSet());
        var plan = SubjectPlan.empty();
        for (long fileId : command.evidenceFileIds()) {
            if (!authorized.contains(fileId)) {
                continue;
            }
            plan = plan.merge(SubjectPlan.resource(new LockPlan.Key(LockPlan.Domain.FILE_RECORD, List.of(fileId)),
                    transaction -> {
                        try {
                            files.lockFiles(List.of(fileId));
                        } catch (FileRegistry.Rejected rejected) {
                            throw evidenceError(rejected);
                        }
                    }));
        }
        return plan;
    }

    /**
     * Binds caller-authorized case evidence through the real S1 file service. The case module
     * supplies the owner and slot; the application never trusts a caller-supplied owner. Existing
     * references with the same file, target and slot are reused.
     */
    private List<FileReferences.Reference> attachEvidence(EnforcementCommand command, CaseAccess access) {
        if (command.evidenceFileIds().isEmpty()) {
            return List.of();
        }
        Map<Long, CaseEvidence> authorized = access.evidence().stream()
                .collect(Collectors.toMap(CaseEvidence::fileId, Function.identity(), (first, second) -> first));
        var target = new UploadRegistration.Target("case", command.caseId());
        var references = new ArrayList<FileReferences.Reference>();
        for (long fileId : command.evidenceFileIds()) {
            var evidence = authorized.get(fileId);
            if (evidence == null) {
                throw new BusinessError("EVIDENCE_OUT_OF_SCOPE", 422, "证据文件不属于本事项");
            }
            try {
                references.addAll(files.attach(evidence.ownerAccountId(), target, FilePurpose.CASE_EVIDENCE,
                        List.of(fileId), evidence.slot()));
            } catch (FileRegistry.Rejected rejected) {
                throw evidenceError(rejected);
            }
        }
        return List.copyOf(references);
    }

    private static BusinessError evidenceError(FileRegistry.Rejected rejected) {
        String code = rejected.getMessage();
        int status = "RESOURCE_NOT_VISIBLE".equals(code) ? 404 : 422;
        return new BusinessError(code, status, "证据文件不可引用");
    }

    private SubjectResult apply(WriteTransaction transaction, EnforcementCommand command,
                                EnforcementInstruction instruction, CaseAccess access) {
        var subject = SubjectCommand.of(command, instruction, access);
        return switch (instruction.action()) {
            case RESTRICT_ACCOUNT -> restrictAccount(transaction, subject);
            case LIFT_ACCOUNT_RESTRICTION -> liftAccount(transaction, subject);
            case WITHDRAW_PUBLIC_ACCESS -> withdrawPublicAccess(transaction, subject);
            case RESTORE_DISPLAY -> products.restore(transaction, subject);
            case REMOVE_CONTENT -> switch (instruction.target().type()) {
                case "comment" -> products.removeContent(transaction, subject);
                case "evaluation" -> trades.removeEvaluation(transaction, subject);
                default -> throw new BusinessError("TARGET_INVALID", 422, "内容目标类型无效");
            };
            case FREEZE_TRADE -> appendTradeEvent(transaction, subject, "trade_frozen",
                    trades.freeze(transaction, subject));
            case LIFT_TRADE_FREEZE -> appendTradeEvent(transaction, subject, "trade_unfrozen",
                    trades.liftFreeze(transaction, subject));
            case ADJUST_TRADE_STATUS -> adjustTrade(transaction, subject);
            case REMOVE_EVALUATION_CONTENT -> trades.removeEvaluation(transaction, subject);
        };
    }

    private SubjectResult restrictAccount(WriteTransaction transaction, SubjectCommand command) {
        var account = accounts.restrict(transaction, command);
        if (account.result().alreadyEffective()) {
            return account.result();
        }
        var product = products.restrictForAccount(transaction, command, account.restrictionRef(),
                account.productRefs());
        var trade = trades.freezeForAccount(transaction, command, account.restrictionRef(), account.tradeRefs());
        var closed = trades.closeRequests(transaction, command, account.requestRefs());
        var conversation = conversations.archiveRequestBranches(transaction, command, account.requestRefs());
        return SubjectResult.combine(account.result(), product, trade, closed, conversation);
    }

    private SubjectResult liftAccount(WriteTransaction transaction, SubjectCommand command) {
        var account = accounts.lift(transaction, command);
        if (account.result().alreadyEffective()) {
            return account.result();
        }
        var product = products.restoreForAccount(transaction, command, account.restrictionRef(),
                account.productRefs());
        var tradesRestored = trades.liftAccountFreeze(transaction, command, account.restrictionRef());
        return SubjectResult.combine(account.result(), product, tradesRestored);
    }

    private SubjectResult withdrawPublicAccess(WriteTransaction transaction, SubjectCommand command) {
        var product = products.withdraw(transaction, command);
        if (product.result().alreadyEffective()) {
            return product.result();
        }
        var trade = trades.closeRequests(transaction, command, product.requestRefs());
        var conversation = conversations.archiveRequestBranches(transaction, command, product.requestRefs());
        return SubjectResult.combine(product.result(), trade, conversation);
    }

    private SubjectResult appendTradeEvent(WriteTransaction transaction, SubjectCommand command,
                                           String eventType, SubjectResult trade) {
        if (trade.alreadyEffective()) {
            return trade;
        }
        var conversation = conversations.appendTradeEvent(transaction, command, eventType, trade.result());
        return SubjectResult.combine(trade, conversation);
    }

    private SubjectResult adjustTrade(WriteTransaction transaction, SubjectCommand command) {
        var adjustment = trades.adjustStatus(transaction, command);
        if (adjustment.result().alreadyEffective()) {
            return adjustment.result();
        }
        var trade = adjustment.result();
        var message = conversations.appendTradeEvent(transaction, command, adjustment.eventType(), trade.result());
        if (adjustment.terminal()) {
            var archived = conversations.archiveTradeConversation(transaction, command, trade.result());
            return SubjectResult.combine(trade, message, archived);
        }
        return SubjectResult.combine(trade, message);
    }

    private static EnforcementOutcome outcome(EnforcementInstruction instruction, SubjectResult result,
                                              Instant occurredAt) {
        instruction.action().requireResult(instruction.target(), result.result());
        return new EnforcementOutcome(instruction.enforcementId(), instruction.action(), instruction.target(),
                result.result(), result.previousState(), result.currentState(), result.affectedScope(), occurredAt,
                result.alreadyEffective() ? EnforcementOutcome.Status.REPLAYED : EnforcementOutcome.Status.APPLIED);
    }

    private void audit(WriteTransaction transaction, CaseAccess access, EnforcementOutcome outcome) {
        var facts = json.createObjectNode();
        facts.put("enforcement_id", outcome.enforcementId());
        facts.set("result_ref", json.valueToTree(outcome.result()));
        facts.put("previous_state", outcome.previousState());
        facts.put("current_state", outcome.currentState());
        facts.set("basis_refs", json.valueToTree(access.basis()));
        transaction.audit(outcome.action().operationName(), outcome.target(), access.caseRef(), facts);
    }

    private static boolean allPrior(EnforcementCommand command, CaseAccess access) {
        return command.enforcements().stream()
                .allMatch(instruction -> access.priorExecutions().containsKey(instruction.enforcementId()));
    }

    /**
     * C3 registry event labels. The notification adapter maps them onto the S1 event-intent
     * naming rule without changing the shared C1 contract.
     */
    private static Notification notification(EnforcementAction action) {
        return switch (action) {
            case RESTRICT_ACCOUNT -> new Notification("case.account_restricted", "restricted");
            case LIFT_ACCOUNT_RESTRICTION -> new Notification("case.account_restriction_lifted", "lifted");
            case WITHDRAW_PUBLIC_ACCESS -> new Notification("case.display_withdrawn", "withdrawn");
            case RESTORE_DISPLAY -> new Notification("case.display_restored", "restored");
            case REMOVE_CONTENT -> new Notification("case.content_removed", "removed");
            case REMOVE_EVALUATION_CONTENT -> new Notification("case.evaluation_removed", "evaluated");
            case FREEZE_TRADE -> new Notification("case.trade_frozen", "frozen");
            case LIFT_TRADE_FREEZE -> new Notification("case.trade_unfrozen", "unfrozen");
            case ADJUST_TRADE_STATUS -> new Notification("case.trade_adjusted", "adjusted");
        };
    }

    private record PendingNotification(EnforcementOutcome outcome, Set<Long> recipients) {}

    private record Notification(String eventType, String suffix) {}
}
