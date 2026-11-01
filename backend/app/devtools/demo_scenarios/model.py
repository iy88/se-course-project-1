"""持久演示场景的数据模型。

本模块只描述“预置什么”，不写数据库、不依赖测试代码。``catalog.py`` 用这些
结构声明一套可追踪的校园场景；``builder.py`` 负责落库，``checks.py`` 负责静态
校验与只读核验。场景 key、对象 key 与 manifest 中的记录一一对应，避免 seed
和自动化测试各自复制一份相似的文案。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccountSpec:
    """演示身份。显示名使用虚构的“专业年级 + 姓名”风格，不含真实联系方式。"""

    key: str
    display_name: str
    role: str = "user"
    persona: str = ""


@dataclass(frozen=True)
class AliasSpec:
    key: str
    name: str
    days_ago: float
    removed_days_ago: float | None = None


@dataclass(frozen=True)
class CategorySpec:
    key: str
    name: str
    created_by: str
    days_ago: float
    aliases: tuple[AliasSpec, ...] = ()
    disabled_days_ago: float | None = None
    deleted_days_ago: float | None = None


@dataclass(frozen=True)
class ProhibitedSpec:
    key: str
    group_name: str
    content: str
    updated_by: str
    days_ago: float
    sort: int = 0


@dataclass(frozen=True)
class ReviewSpec:
    """一次商品内容审核。重提会形成新的 ReviewSpec / 新事项。"""

    result: str  # approved / rejected / pending / withdrawn
    days_ago: float
    reason: str | None = None
    reviewer: str | None = "admin"
    claimed_by: str | None = None  # 仅 pending：事项是否已被认领
    claimed_days_ago: float | None = None
    key: str = ""  # 可选稳定对象 key；为空时由商品与序号生成
    case_key: str = ""  # 可选审核事项 key


@dataclass(frozen=True)
class TagApplicationSpec:
    requested_name: str
    status: str = "pending"
    days_ago: float = 1
    resolved_category: str | None = None
    reason: str | None = None
    decided_days_ago: float | None = None
    key: str = ""


@dataclass(frozen=True)
class EditSpec:
    editor: str
    reason: str
    days_ago: float
    before: dict
    after: dict
    edit_type: str = "edit"
    key: str = ""


@dataclass(frozen=True)
class CommentSpec:
    key: str
    author: str
    content: str
    days_ago: float
    reply_to: str | None = None
    deleted_by: str | None = None
    delete_reason: str | None = None
    deleted_days_ago: float | None = None


@dataclass(frozen=True)
class ProductSpec:
    key: str
    seller: str
    title: str
    description: str
    price_cents: int
    status: str
    category: str
    asset: str
    created_days_ago: float
    listed_days_ago: float | None = None
    delisted_days_ago: float | None = None
    reject_reason: str | None = None
    tags: tuple[str, ...] = ()
    reviews: tuple[ReviewSpec, ...] = ()
    tag_apps: tuple[TagApplicationSpec, ...] = ()
    edits: tuple[EditSpec, ...] = ()
    comments: tuple[CommentSpec, ...] = ()
    favorites: tuple[str, ...] = ()
    display_restricted: bool = False
    restricted_case: str | None = None
    restricted_days_ago: float | None = None
    restricted_reason: str | None = None
    image_slug: str | None = None  # 默认使用 key

    @property
    def all_tags(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.category, *self.tags)))


@dataclass(frozen=True)
class AgreementSpec:
    round_no: int
    proposer: str
    delivery_time: str
    delivery_location: str
    delivery_method: str
    amount_cents: int
    payment_method: str
    payment_timing: str
    status: str
    proposed_days_ago: float
    decided_days_ago: float | None = None


@dataclass(frozen=True)
class ConfirmationSpec:
    confirmer: str
    days_ago: float
    is_current: bool = True
    note: str | None = None
    key: str = ""


@dataclass(frozen=True)
class TradeReviewSpec:
    reviewer: str
    rating: int
    content: str
    days_ago: float
    key: str = ""
    deleted_by: str | None = None
    delete_reason: str | None = None
    deleted_days_ago: float | None = None


@dataclass(frozen=True)
class TransitionSpec:
    from_status: str | None
    to_status: str
    trigger: str
    actor: str | None
    actor_role: str
    days_ago: float
    reason: str | None = None
    basis_case: str | None = None


@dataclass(frozen=True)
class MessageSpec:
    sender: str | None  # None 表示系统消息
    content: str
    days_ago: float


@dataclass(frozen=True)
class TradeSpec:
    key: str
    product: str
    buyer: str
    status: str
    created_days_ago: float
    accepted_days_ago: float | None = None
    finished_days_ago: float | None = None
    request_note: str | None = None
    close_reason: str | None = None
    agreements: tuple[AgreementSpec, ...] = ()
    current_round: int | None = None
    confirmations: tuple[ConfirmationSpec, ...] = ()
    reviews: tuple[TradeReviewSpec, ...] = ()
    confirm_wait_started_days_ago: float | None = None
    cancel_requested_by: str | None = None
    cancel_requested_days_ago: float | None = None
    resolution_confirmed_by: str | None = None
    resolution_confirmed_days_ago: float | None = None
    frozen: bool = False
    frozen_reason: str | None = None
    frozen_by: str | None = None
    frozen_days_ago: float | None = None
    frozen_case: str | None = None
    finished_by: str | None = None
    finished_trigger: str | None = None
    finished_reason: str | None = None
    finished_case: str | None = None
    messages: tuple[MessageSpec, ...] = ()
    reads: tuple[tuple[str, int], ...] = ()  # (账号 key, 已读到的消息序号，1 起)
    history: tuple[TransitionSpec, ...] = ()  # 首尾之外的中间状态转换
    case: CaseSpec | None = None


@dataclass(frozen=True)
class CaseMessageSpec:
    sender: str | None
    role: str
    kind: str
    content: str
    days_ago: float


@dataclass(frozen=True)
class CaseSpec:
    key: str
    case_type: str
    title: str
    created_days_ago: float
    status: str = "pending"
    subject: str | None = None
    claimed_by: str | None = None
    claimed_days_ago: float | None = None
    conclusion: str | None = None
    conclusion_reason: str | None = None
    basis: str | None = None
    disposed_days_ago: float | None = None
    messages: tuple[CaseMessageSpec, ...] = ()


@dataclass(frozen=True)
class EvidenceSpec:
    slug: str
    asset: str
    kind: str = "report"  # report / supplement


@dataclass(frozen=True)
class SupplementSpec:
    key: str
    author: str
    content: str
    days_ago: float
    evidence: tuple[EvidenceSpec, ...] = ()


@dataclass(frozen=True)
class ReportSpec:
    key: str
    reporter: str
    target_type: str
    target: str  # 商品/评论/消息/评价/用户的对象 key
    reason: str
    days_ago: float
    detail: str | None = None
    status: str = "pending"
    result_confirmed: bool = False
    public_result: str | None = None
    result_reason: str | None = None
    closed_days_ago: float | None = None
    evidence: tuple[EvidenceSpec, ...] = ()
    supplements: tuple[SupplementSpec, ...] = ()
    case: CaseSpec | None = None


@dataclass(frozen=True)
class RestrictionSpec:
    key: str
    user: str
    reason: str
    basis: str | None
    case: str
    created_by: str
    days_ago: float
    status: str = "active"
    lifted_by: str | None = None
    lift_reason: str | None = None
    lifted_days_ago: float | None = None


@dataclass(frozen=True)
class NotificationSpec:
    key: str
    user: str
    type: str
    title: str
    content: str
    days_ago: float
    link_type: str | None = None
    link: str | None = None  # 场景对象 key
    payload: dict = field(default_factory=dict)
    is_read: bool = False
    read_days_ago: float | None = None


@dataclass(frozen=True)
class NormalConversationSpec:
    key: str
    users: tuple[str, str]
    created_days_ago: float
    messages: tuple[MessageSpec, ...]
    reads: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class AvatarSpec:
    user: str
    asset: str
    slug: str
    days_ago: float
    case: CaseSpec
    content_note: str = ""


@dataclass(frozen=True)
class ScenarioSpec:
    """一条可独立演示的业务路线。

    ``objects`` 是本场景现场操作的入口对象；同一对象只能属于一个场景，互斥分支
    必须使用不同对象。``checks`` 是自动化与只读核验共同引用的断言标识。
    """

    key: str
    title: str
    area: str
    roles: tuple[str, ...]
    initial_state: str
    timeline: tuple[str, ...]
    data_summary: str
    actions: tuple[str, ...]
    expected: tuple[str, ...]
    mappings: tuple[str, ...]
    exclusive_with: tuple[str, ...]
    checks: tuple[str, ...]
    objects: tuple[str, ...]
    live_start: bool = True
    note: str = ""
