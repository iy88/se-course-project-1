package io.github.iy88.project1.casemanagement.application;

import io.github.iy88.project1.core.ResourceRef;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * Result returned by a subject capability. {@code alreadyEffective} means the same source was
 * already applied; the application must then reuse the result and must not emit a new
 * notification or audit.
 */
public record SubjectResult(ResourceRef result, String previousState, String currentState,
                            List<ResourceRef> affectedScope, Set<Long> recipientAccountIds,
                            boolean alreadyEffective) {
    public SubjectResult {
        Objects.requireNonNull(result);
        affectedScope = List.copyOf(affectedScope);
        recipientAccountIds = Set.copyOf(recipientAccountIds);
    }

    public static SubjectResult of(ResourceRef result, String previousState, String currentState) {
        return new SubjectResult(result, previousState, currentState, List.of(), Set.of(), false);
    }

    public SubjectResult withRecipients(Set<Long> recipients) {
        return new SubjectResult(result, previousState, currentState, affectedScope, recipients, alreadyEffective);
    }

    public SubjectResult withAffectedScope(List<ResourceRef> scope) {
        return new SubjectResult(result, previousState, currentState, scope, recipientAccountIds, alreadyEffective);
    }

    /** Keeps the primary action's recipients; related business notifications belong to their owners. */
    public static SubjectResult combine(SubjectResult primary, SubjectResult... additional) {
        var scope = new ArrayList<>(primary.affectedScope());

        for (var result : additional) {
            scope.addAll(result.affectedScope());
        }
        return new SubjectResult(primary.result(), primary.previousState(), primary.currentState(),
                scope.stream().distinct().toList(), primary.recipientAccountIds(), primary.alreadyEffective());
    }
}
