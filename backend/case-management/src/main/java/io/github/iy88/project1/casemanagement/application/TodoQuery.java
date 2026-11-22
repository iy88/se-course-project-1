package io.github.iy88.project1.casemanagement.application;

/** Read-side queue parameters after HTTP pagination validation. */
public record TodoQuery(long managerId, TodoOwnership ownership, String kind, int page, int pageSize) {}
