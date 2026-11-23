package io.github.iy88.project1.casemanagement;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Limits and the appeal window of the case lifecycle. Values stay configurable. */
@ConfigurationProperties("project1.case")
public class CaseSettings {
    private int appealWindowSeconds = 604800;
    private int maxReasonLength = 500;
    private int maxNoteLength = 2000;
    private int maxPageSize = 100;
    private int defaultPageSize = 20;

    public int getAppealWindowSeconds() {
        return appealWindowSeconds;
    }

    public void setAppealWindowSeconds(int appealWindowSeconds) {
        if (appealWindowSeconds < 0) {
            throw new IllegalArgumentException("appealWindowSeconds must not be negative");
        }
        this.appealWindowSeconds = appealWindowSeconds;
    }

    public int getMaxReasonLength() {
        return maxReasonLength;
    }

    public void setMaxReasonLength(int maxReasonLength) {
        if (maxReasonLength <= 0) {
            throw new IllegalArgumentException("maxReasonLength must be positive");
        }
        this.maxReasonLength = maxReasonLength;
    }

    public int getMaxNoteLength() {
        return maxNoteLength;
    }

    public void setMaxNoteLength(int maxNoteLength) {
        if (maxNoteLength <= 0) {
            throw new IllegalArgumentException("maxNoteLength must be positive");
        }
        this.maxNoteLength = maxNoteLength;
    }

    public int getMaxPageSize() {
        return maxPageSize;
    }

    public void setMaxPageSize(int maxPageSize) {
        if (maxPageSize <= 0) {
            throw new IllegalArgumentException("maxPageSize must be positive");
        }
        this.maxPageSize = maxPageSize;
    }

    public int getDefaultPageSize() {
        return defaultPageSize;
    }

    public void setDefaultPageSize(int defaultPageSize) {
        if (defaultPageSize <= 0) {
            throw new IllegalArgumentException("defaultPageSize must be positive");
        }
        this.defaultPageSize = defaultPageSize;
    }
}
