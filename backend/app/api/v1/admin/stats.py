"""管理统计（FR-10/BR-31）：账户、商品状态、待办与交易结果，时间范围或全部。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models import (
    DisposalCase,
    Product,
    Trade,
    User,
)
from app.models.enums import (
    AccountStatus,
    CaseStatus,
    CaseType,
    ProductStatus,
    TradeStatus,
)

router = APIRouter(prefix="/admin/stats", tags=["admin-stats"])


def _parse_date(value: str | None, end_of_day: bool = False):
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=UTC)


@router.get("")
async def stats(
    admin: CurrentAdmin,
    db: DbSession,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict:
    """BR-31：不统计真实付款金额；状态数按查询时点，时间范围按结果确认时间。"""
    users_total = await db.scalar(select(func.count()).select_from(User)) or 0
    banned_total = await db.scalar(
        select(func.count()).select_from(User).where(User.status == AccountStatus.BANNED.value)
    ) or 0
    product_counts = {}
    for status_value in ProductStatus:
        product_counts[status_value.value] = await db.scalar(
            select(func.count()).select_from(Product).where(Product.status == status_value.value)
        ) or 0
    restricted_products = await db.scalar(
        select(func.count()).select_from(Product).where(Product.display_restricted.is_(True))
    ) or 0
    pending_reviews = await db.scalar(
        select(func.count()).select_from(DisposalCase).where(
            DisposalCase.case_type == CaseType.PRODUCT_REVIEW.value,
            DisposalCase.status != CaseStatus.DISPOSED.value,
        )
    ) or 0
    pending_reports = await db.scalar(
        select(func.count()).select_from(DisposalCase).where(
            DisposalCase.case_type == CaseType.REPORT.value,
            DisposalCase.status != CaseStatus.DISPOSED.value,
        )
    ) or 0
    pending_cases_total = await db.scalar(
        select(func.count()).select_from(DisposalCase).where(DisposalCase.status != CaseStatus.DISPOSED.value)
    ) or 0
    trade_counts = {}
    for status_value in TradeStatus:
        trade_counts[status_value.value] = await db.scalar(
            select(func.count()).select_from(Trade).where(Trade.status == status_value.value)
        ) or 0
    frozen_trades = await db.scalar(
        select(func.count()).select_from(Trade).where(
            Trade.frozen.is_(True), Trade.status.in_(["in_progress", "disputed", "abnormal"])
        )
    ) or 0

    range_completed = None
    if date_from or date_to:
        start = _parse_date(date_from) or datetime(1970, 1, 1, tzinfo=UTC)
        end = _parse_date(date_to, end_of_day=True) or datetime.now(UTC)
        range_completed = await db.scalar(
            select(func.count()).select_from(Trade).where(
                Trade.status == TradeStatus.COMPLETED.value,
                Trade.finished_at >= start,
                Trade.finished_at <= end,
            )
        ) or 0

    return {
        "users": {"total": int(users_total), "banned": int(banned_total)},
        "products": {**product_counts, "display_restricted": int(restricted_products)},
        "pending": {
            "review_cases": int(pending_reviews),
            "report_cases": int(pending_reports),
            "all_cases": int(pending_cases_total),
        },
        "trades": {**trade_counts, "frozen_current": int(frozen_trades)},
        "range": {
            "from": date_from,
            "to": date_to,
            "completed_trades": int(range_completed) if range_completed is not None else None,
        },
    }
