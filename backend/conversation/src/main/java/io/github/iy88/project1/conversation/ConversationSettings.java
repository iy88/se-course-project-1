package io.github.iy88.project1.conversation;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Conversation limits stay configurable so rules can change without a schema change. */
@ConfigurationProperties("project1.conversation")
public class ConversationSettings {
    private int maxBodyLength = 2000;
    private int maxPageSize = 100;
    private int previewLength = 50;

    public int getMaxBodyLength() {
        return maxBodyLength;
    }

    public void setMaxBodyLength(int maxBodyLength) {
        if (maxBodyLength <= 0) {
            throw new IllegalArgumentException("maxBodyLength must be positive");
        }
        this.maxBodyLength = maxBodyLength;
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

    public int getPreviewLength() {
        return previewLength;
    }

    public void setPreviewLength(int previewLength) {
        if (previewLength <= 0) {
            throw new IllegalArgumentException("previewLength must be positive");
        }
        this.previewLength = previewLength;
    }
}
