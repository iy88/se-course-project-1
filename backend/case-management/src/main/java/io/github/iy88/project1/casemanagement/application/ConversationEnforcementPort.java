package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import io.github.iy88.project1.core.WriteTransaction;
import java.util.List;

/** Conversation-owned system message and archive capability. */
public interface ConversationEnforcementPort {
    SubjectPlan prepare(SubjectCommand command);

    SubjectResult appendTradeEvent(WriteTransaction transaction, SubjectCommand command,
                                   String eventType, ResourceRef sourceRef);

    SubjectResult archiveTradeConversation(WriteTransaction transaction, SubjectCommand command,
                                           ResourceRef sourceRef);

    SubjectResult archiveRequestBranches(WriteTransaction transaction, SubjectCommand command,
                                         List<ResourceRef> requestRefs);
}
