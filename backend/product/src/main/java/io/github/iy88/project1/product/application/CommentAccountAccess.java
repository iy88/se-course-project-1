package io.github.iy88.project1.product.application;

import java.util.Map;
import java.util.Set;

/**
 * Reads the account facts product interaction rendering needs. The account module owns identity and
 * restrictions; the product module only asks for display names and the current write restriction.
 */
public interface CommentAccountAccess {
    Map<Long, String> displayNames(Set<Long> accountIds);

    boolean writeRestricted(long accountId);
}
