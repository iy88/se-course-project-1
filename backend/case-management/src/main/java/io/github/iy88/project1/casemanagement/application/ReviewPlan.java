package io.github.iy88.project1.casemanagement.application;

/** Product-side lock candidates plus the case id derived from the audit's unique link. */
public record ReviewPlan(SubjectPlan locks, long caseId) {}
