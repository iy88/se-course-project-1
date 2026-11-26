package io.github.iy88.project1.conversation;

/** The three conversation tables share no identifiers; callers always supply the kind. */
public enum ConversationKind {
    CHAT("chat"),
    TRADE("trade"),
    CASE("case");

    private final String wireValue;

    ConversationKind(String wireValue) {
        this.wireValue = wireValue;
    }

    public String wireValue() {
        return wireValue;
    }
}
