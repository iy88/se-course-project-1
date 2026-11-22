package io.github.iy88.project1.conversation;

/** Case threads keep the speaking role in the message so a thread never infers it from context. */
public enum CaseMessageKind {
    INQUIRY,
    STATEMENT,
    APPEAL,
    MANAGER_REPLY,
    SYSTEM_NOTICE
}
