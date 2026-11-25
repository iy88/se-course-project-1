package io.github.iy88.project1.trade.domain;

import java.util.Locale;

/** Stable business vocabulary for the trade lifecycle. */
public final class TradeVocabulary {
    private TradeVocabulary() {
    }

    public enum AgreementStatus {
        PROPOSED, EFFECTIVE, REJECTED, WITHDRAWN, SUPERSEDED;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static AgreementStatus from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum Decision {
        ACCEPT, REJECT, WITHDRAW;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static Decision from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum CancellationMode {
        DIRECT, APPROVAL;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static CancellationMode from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum CancellationStatus {
        PENDING, ACCEPTED, REJECTED, WITHDRAWN;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static CancellationStatus from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum DisputeStatus {
        OPEN, RESOLVED, TERMINATED;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static DisputeStatus from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum ResolutionMode {
        SELF, ADMIN;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static ResolutionMode from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum FreezeSource {
        TIMEOUT, ADMIN_CASE, ACCOUNT_BAN;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static FreezeSource from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum WaitEndReason {
        COMPLETED, AGREEMENT_CHANGED, DISPUTED, TERMINATED, TIMEOUT, ADMIN_RESTORED;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static WaitEndReason from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum InvalidationReason {
        AGREEMENT_CHANGED, DISPUTE_RESOLVED, ADMIN_RESTORED;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static InvalidationReason from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum CloseReason {
        OTHER_USER_LOCKED, PRODUCT_DELISTED, PUBLIC_ACCESS_REVOKED, ACCOUNT_BANNED;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static CloseReason from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum TerminalReason {
        COMPLETED, CANCELLED, ADMIN_TERMINATED;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static TerminalReason from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }

    public enum ActorKind {
        BUYER, SELLER, ADMIN, SYSTEM;

        public String value() { return name().toLowerCase(Locale.ROOT); }

        public static ActorKind from(String value) { return valueOf(value.toUpperCase(Locale.ROOT)); }
    }
}
