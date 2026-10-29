"""业务枚举：状态与类型统一在此定义（对齐需求 BR/TR 与第 5 章状态分析）。"""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    NORMAL = "normal"
    BANNED = "banned"  # C-14 封禁生效


class ProductStatus(StrEnum):
    """商品生命周期（TR-01—TR-08）；展示限制单独字段，不混入生命周期。"""

    PENDING_REVIEW = "pending_review"  # 待审核
    REJECTED = "rejected"  # 审核未通过
    LISTED = "listed"  # 公开可交易
    IN_TRANSACTION = "in_transaction"  # 交易中
    DELISTED = "delisted"  # 已下架


class ReviewResult(StrEnum):
    """C-04 审核记录结论（退回补充作为不通过原因记录；撤回仅结束该次审核记录）。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"  # 卖方在认领前撤回，商品置为已下架（D-46，非商品生命周期状态）


class TradeStatus(StrEnum):
    """C-09 交易生命周期（TR-11—TR-19）。"""

    PENDING_ACCEPTANCE = "pending_acceptance"  # 待接受
    REJECTED = "rejected"  # 已拒绝
    WITHDRAWN = "withdrawn"  # 已撤回
    CLOSED = "closed"  # 已关闭（其他用户锁单/商品下架）
    IN_PROGRESS = "in_progress"  # 进行中
    DISPUTED = "disputed"  # 有争议
    ABNORMAL = "abnormal"  # 异常交易（单方确认超时）
    TERMINATED = "terminated"  # 已终止（计失败）
    COMPLETED = "completed"  # 已完成


# 进行中/仍锁单的交易状态：同一商品同时至多一笔
LOCKING_TRADE_STATUSES = (
    TradeStatus.IN_PROGRESS,
    TradeStatus.DISPUTED,
    TradeStatus.ABNORMAL,
)

# 已结束的交易状态：解除锁单、归档分支、解本笔冻结
ENDED_TRADE_STATUSES = (
    TradeStatus.COMPLETED,
    TradeStatus.TERMINATED,
)


class AgreementStatus(StrEnum):
    PROPOSED = "proposed"  # 已提出待对方确认
    CONFIRMED = "confirmed"  # 已确认生效
    REJECTED = "rejected"  # 被拒绝（仅结束该次提案）
    SUPERSEDED = "superseded"  # 被后续确认的变更替换


class ConversationType(StrEnum):
    NORMAL = "normal"  # 普通私聊（按双人复用）
    TRADE = "trade"  # 交易分支（按笔独立）


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
    PENDING = "pending"  # 待处理（共享池）
    PROCESSING = "processing"  # 处理中（已认领）
    UNFOUNDED = "unfounded"  # 无法认定/不予处理
    HANDLED = "handled"  # 认定违规并处置


class CaseType(StrEnum):
    PRODUCT_REVIEW = "product_review"  # 商品审核事项
    REPORT = "report"  # 举报事项
    TRADE_DISPUTE = "trade_dispute"  # 交易争议
    ABNORMAL_TRADE = "abnormal_trade"  # 异常交易
    ACCOUNT_BAN = "account_ban"  # 账户封禁事项


class CaseStatus(StrEnum):
    PENDING = "pending"  # 待处理（共享池）
    PROCESSING = "processing"  # 处理中（已认领）
    DISPOSED = "disposed"  # 已处置


class DisposalMessageRole(StrEnum):
    ADMIN = "admin"
    USER = "user"
    SYSTEM = "system"


class DisposalMessageKind(StrEnum):
    INQUIRY = "inquiry"  # 管理员问询
    STATEMENT = "statement"  # 用户说明（问询阶段）
    APPEAL = "appeal"  # 用户申辩（处置后）
    REPLY = "reply"  # 管理员回复结论
    NOTICE = "notice"  # 系统留痕（处置/解除等通知记录）


class RestrictionType(StrEnum):
    BAN = "ban"  # 账户封禁（C-14）；交易冻结由 trades.frozen 表达


class RestrictionStatus(StrEnum):
    ACTIVE = "active"
    LIFTED = "lifted"


class NotificationType(StrEnum):
    REVIEW_RESULT = "review_result"  # 审核通过/未过
    REQUEST_CREATED = "request_created"  # 成功购买请求（→卖方）
    REQUEST_ACCEPTED = "request_accepted"
    REQUEST_REJECTED = "request_rejected"
    REQUEST_CLOSED = "request_closed"  # 其他用户锁单/商品下架
    REQUEST_WITHDRAWN = "request_withdrawn"
    AGREEMENT_PROPOSED = "agreement_proposed"  # 提出约定/变更（→对方）
    AGREEMENT_DECIDED = "agreement_decided"  # 对方同意/拒绝约定（→提出方）
    CONFIRM_PROGRESS = "confirm_progress"  # 单方完成确认（→另一方）
    TRADE_COMPLETED = "trade_completed"
    CANCEL_REQUESTED = "cancel_requested"  # 取消申请待确认
    TRADE_TERMINATED = "trade_terminated"
    PRODUCT_EDITED = "product_edited"  # 商品编辑（→未结束请求/交易买方）
    TRADE_FROZEN = "trade_frozen"  # 冻结/管理调整（→双方）
    TRADE_UNFROZEN = "trade_unfrozen"
    TRADE_ADJUSTED = "trade_adjusted"
    TRADE_DISPUTE = "trade_dispute"  # 对方发起争议
    DISPUTE_RESOLVED = "dispute_resolved"
    TRADE_ABNORMAL = "trade_abnormal"  # 超时转异常（→双方）
    REPORT_RESULT = "report_result"  # 举报处理确认（→举报人）
    INQUIRY = "inquiry"  # 问询（→被询问用户）
    DISPOSAL = "disposal"  # 实际处置（→受影响者）
    APPEAL_RESULT = "appeal_result"  # 申辩处理结果（→申辩用户）


class AdminActionType(StrEnum):
    """管理动作留痕类型（写入处置/状态转移依据）。"""

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
