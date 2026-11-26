package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.List;

/** Trade-owned freeze, status, request-close and evaluation capability. */
public interface TradeEnforcementPort {
    /** Includes linked request, product, trade and conversation keys where the action needs them. */
    SubjectPlan prepare(SubjectCommand command);

    SubjectResult freeze(WriteTransaction transaction, SubjectCommand command);

    SubjectResult liftFreeze(WriteTransaction transaction, SubjectCommand command);

    Adjustment adjustStatus(WriteTransaction transaction, SubjectCommand command);

    /** Closes pending requests and records their trade notifications. The case flow archives their branches. */
    SubjectResult closeRequests(WriteTransaction transaction, SubjectCommand command,
                                List<ResourceRef> requestRefs);

    /** Applies the account source and registers each affected trade's own status event and notification. */
    SubjectResult freezeForAccount(WriteTransaction transaction, SubjectCommand command,
                                   ResourceRef restrictionRef, List<ResourceRef> trades);

    /** Releases only freezes contributed by this account restriction, then rechecks remaining restrictions. */
    SubjectResult liftAccountFreeze(WriteTransaction transaction, SubjectCommand command, ResourceRef restrictionRef);

    SubjectResult removeEvaluation(WriteTransaction transaction, SubjectCommand command);

    record Adjustment(SubjectResult result, String eventType, boolean terminal) {}
}
