package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.List;

/** Product-owned display, content and account-restriction projection capability. */
public interface ProductEnforcementPort {
    SubjectPlan prepare(SubjectCommand command);

    Withdrawal withdraw(WriteTransaction transaction, SubjectCommand command);

    SubjectResult restore(WriteTransaction transaction, SubjectCommand command);

    SubjectResult removeContent(WriteTransaction transaction, SubjectCommand command);

    SubjectResult restrictForAccount(WriteTransaction transaction, SubjectCommand command,
                                     ResourceRef restrictionRef, List<ResourceRef> products);

    SubjectResult restoreForAccount(WriteTransaction transaction, SubjectCommand command,
                                    ResourceRef restrictionRef, List<ResourceRef> products);

    record Withdrawal(SubjectResult result, List<ResourceRef> requestRefs) {
        public Withdrawal {
            requestRefs = List.copyOf(requestRefs);
        }
    }
}
