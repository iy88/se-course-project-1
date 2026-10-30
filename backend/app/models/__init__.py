"""模型汇总：导入全部模型以便 create_all 建表。"""

from app.models.audit import AuditEvent
from app.models.category import Category, CategoryAlias
from app.models.governance import (
    DisposalCase,
    DisposalMessage,
    Notification,
    Report,
    ReportSupplement,
)
from app.models.im import Conversation, ConversationRead, Message
from app.models.product import (
    Comment,
    Favorite,
    Product,
    ProductEditHistory,
    ProductImage,
    ProductTag,
    ProductTagApplication,
    ProhibitedItem,
    ReviewRecord,
)
from app.models.stored_object import StoredObject
from app.models.trade import (
    CompletionConfirmation,
    Trade,
    TradeAgreement,
    TradeReview,
    TradeTransition,
)
from app.models.user import AccountRestriction, User

__all__ = [
    "AccountRestriction",
    "AuditEvent",
    "Category",
    "CategoryAlias",
    "Comment",
    "CompletionConfirmation",
    "Conversation",
    "ConversationRead",
    "DisposalCase",
    "DisposalMessage",
    "Favorite",
    "Message",
    "Notification",
    "Product",
    "ProductEditHistory",
    "ProductImage",
    "ProductTag",
    "ProductTagApplication",
    "ProhibitedItem",
    "Report",
    "ReportSupplement",
    "ReviewRecord",
    "StoredObject",
    "Trade",
    "TradeAgreement",
    "TradeReview",
    "TradeTransition",
    "UploadLease",
    "User",
]

from app.models.upload_lease import UploadLease
