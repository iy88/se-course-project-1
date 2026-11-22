package io.github.iy88.project1.casemanagement.application;

import java.time.Instant;

/** Product-owned decision facts needed for the response, notification and audit. */
public record DecisionResult(long auditId, long caseId, long productId, long sellerAccountId,
                             String status, String lifecycleState, int contentVersion, int reviewedContentVersion,
                             CategoryApplicationView categoryApplication, Instant decidedAt,
                             String rejectionReason) {}
