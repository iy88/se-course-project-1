package io.github.iy88.project1.casemanagement.application;

/** Public category-application projection returned with review detail and decisions. */
public record CategoryApplicationView(long applicationId, String proposedName, String status) {}
