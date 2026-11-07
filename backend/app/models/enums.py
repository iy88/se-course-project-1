"""Business enums: statuses and types are defined here (aligned with BR/TR requirements and the Chapter 5 state analysis)."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    NORMAL = "normal"
    BANNED = "banned"  # C-14 ban in effect


class ProductStatus(StrEnum):
    """Product lifecycle (TR-01—TR-08); display restriction is a separate field and is not mixed into the lifecycle."""

    PENDING_REVIEW = "pending_review"  # awaiting review
    REJECTED = "rejected"  # review rejected
    LISTED = "listed"  # publicly tradable
    IN_TRANSACTION = "in_transaction"  # in a transaction
    DELISTED = "delisted"  # delisted


class ReviewResult(StrEnum):
    """C-04 review record result (a request for supplements is recorded as a rejection reason; withdrawal only ends that review record)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"  # seller withdrew before claim; the product is set to delisted (D-46, not a product lifecycle status)


class TradeStatus(StrEnum):
    """C-09 trade lifecycle (TR-11—TR-19)."""

    PENDING_ACCEPTANCE = "pending_acceptance"  # awaiting acceptance
    REJECTED = "rejected"  # rejected
    WITHDRAWN = "withdrawn"  # withdrawn
    CLOSED = "closed"  # closed (another user locked the product / product delisted)
    IN_PROGRESS = "in_progress"  # in progress
    DISPUTED = "disputed"  # disputed
    ABNORMAL = "abnormal"  # abnormal trade (unilateral confirmation timed out)
    TERMINATED = "terminated"  # terminated (counted as a failure)
    COMPLETED = "completed"  # completed


# In-progress/still-locking trade statuses: at most one per product at a time
LOCKING_TRADE_STATUSES = (
    TradeStatus.IN_PROGRESS,
    TradeStatus.DISPUTED,
    TradeStatus.ABNORMAL,
)

# Ended trade statuses: release the lock, archive the branch, and unfreeze this trade
ENDED_TRADE_STATUSES = (
    TradeStatus.COMPLETED,
    TradeStatus.TERMINATED,
)


class AgreementStatus(StrEnum):
    PROPOSED = "proposed"  # proposed, awaiting the counterparty
    CONFIRMED = "confirmed"  # confirmed and in effect
    REJECTED = "rejected"  # rejected (ends only that proposal)
    SUPERSEDED = "superseded"  # replaced by a later confirmed change


class ConversationType(StrEnum):
    NORMAL = "normal"  # regular private chat (reused per pair of users)
    TRADE = "trade"  # trade branch (independent per trade)


class MessageKind(StrEnum):
    TEXT = "text"
    SYSTEM = "system"


class ReportTargetType(StrEnum):
    PRODUCT = "product"
    COMMENT = "comment"
    MESSAGE = "message"
    REVIEW = "review"
    USER = "user"


class ReportStatus(StrEnum):
    PENDING = "pending"  # pending (shared pool)
    PROCESSING = "processing"  # processing (claimed)
    UNFOUNDED = "unfounded"  # cannot be established / no action taken
    HANDLED = "handled"  # violation established and handled


class CaseType(StrEnum):
    AVATAR_REVIEW = "avatar_review"
    PRODUCT_REVIEW = "product_review"  # product review case
    REPORT = "report"  # report case
    TRADE_DISPUTE = "trade_dispute"  # trade dispute
    ABNORMAL_TRADE = "abnormal_trade"  # abnormal trade
    ACCOUNT_BAN = "account_ban"  # account ban case


class CaseStatus(StrEnum):
    PENDING = "pending"  # pending (shared pool)
    PROCESSING = "processing"  # processing (claimed)
    DISPOSED = "disposed"  # disposed


class DisposalMessageRole(StrEnum):
    ADMIN = "admin"
    USER = "user"
    SYSTEM = "system"


class DisposalMessageKind(StrEnum):
    INQUIRY = "inquiry"  # administrator inquiry
    STATEMENT = "statement"  # user statement (inquiry stage)
    APPEAL = "appeal"  # user appeal (after disposal)
    REPLY = "reply"  # administrator reply with the conclusion
    NOTICE = "notice"  # system record (notification of disposal/lifting, etc.)


class RestrictionType(StrEnum):
    BAN = "ban"  # account ban (C-14); trade freezing is expressed by trades.frozen


class RestrictionStatus(StrEnum):
    ACTIVE = "active"
    LIFTED = "lifted"


class NotificationType(StrEnum):
    REVIEW_RESULT = "review_result"  # review passed/failed
    REQUEST_CREATED = "request_created"  # purchase request created (→seller)
    REQUEST_ACCEPTED = "request_accepted"
    REQUEST_REJECTED = "request_rejected"
    REQUEST_CLOSED = "request_closed"  # another user locked the product / product delisted
    REQUEST_WITHDRAWN = "request_withdrawn"
    AGREEMENT_PROPOSED = "agreement_proposed"  # agreement/change proposed (→counterparty)
    AGREEMENT_DECIDED = "agreement_decided"  # counterparty accepted/rejected the agreement (→proposer)
    CONFIRM_PROGRESS = "confirm_progress"  # unilateral completion confirmation (→other party)
    TRADE_COMPLETED = "trade_completed"
    CANCEL_REQUESTED = "cancel_requested"  # cancellation request awaiting confirmation
    CANCEL_REJECTED = "cancel_rejected"  # cancellation request rejected by the counterparty
    TRADE_TERMINATED = "trade_terminated"
    PRODUCT_EDITED = "product_edited"  # product edited (→buyer of an unfinished request/trade)
    TRADE_FROZEN = "trade_frozen"  # freeze/administrative adjustment (→both parties)
    TRADE_UNFROZEN = "trade_unfrozen"
    TRADE_ADJUSTED = "trade_adjusted"
    TRADE_DISPUTE = "trade_dispute"  # counterparty opened a dispute
    DISPUTE_RESOLVED = "dispute_resolved"
    TRADE_ABNORMAL = "trade_abnormal"  # timeout turned the trade abnormal (→both parties)
    REPORT_RESULT = "report_result"  # report handling confirmed (→reporter)
    INQUIRY = "inquiry"  # inquiry (→user being asked)
    DISPOSAL = "disposal"  # actual disposal (→affected user)
    APPEAL_RESULT = "appeal_result"  # appeal outcome (→appealing user)


class AdminActionType(StrEnum):
    """Administrative action audit types (recorded as disposal/state-transition basis)."""

    PRODUCT_REVIEW = "product_review"
    CONTENT_REMOVAL = "content_removal"
    ACCOUNT_BAN = "account_ban"
    ACCOUNT_UNBAN = "account_unban"
    TRADE_FREEZE = "trade_freeze"
    TRADE_UNFREEZE = "trade_unfreeze"
    TRADE_ADJUST = "trade_adjust"
    CATEGORY_CORRECTION = "category_correction"
    DISPUTE_RESOLVE = "dispute_resolve"
    DISPLAY_RESTRICT = "display_restrict"
    DISPLAY_RESTORE = "display_restore"
