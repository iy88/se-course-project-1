package io.github.iy88.project1.conversation;

/** System messages have no sending account; managers only exist in case conversations. */
public enum MessageSenderKind {
    ACCOUNT,
    SYSTEM,
    MANAGER
}
