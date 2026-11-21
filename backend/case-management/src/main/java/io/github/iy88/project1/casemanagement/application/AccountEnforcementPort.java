package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.List;

/** Account-owned restriction capability. */
public interface AccountEnforcementPort {
    SubjectPlan prepare(SubjectCommand command);

    Restriction restrict(WriteTransaction transaction, SubjectCommand command);

    Release lift(WriteTransaction transaction, SubjectCommand command);

    record Restriction(SubjectResult result, ResourceRef restrictionRef, List<ResourceRef> productRefs,
                       List<ResourceRef> tradeRefs, List<ResourceRef> requestRefs) {
        public Restriction {
            productRefs = List.copyOf(productRefs);
            tradeRefs = List.copyOf(tradeRefs);
            requestRefs = List.copyOf(requestRefs);
        }
    }

    record Release(SubjectResult result, ResourceRef restrictionRef, List<ResourceRef> productRefs) {
        public Release {
            productRefs = List.copyOf(productRefs);
        }
    }
}
