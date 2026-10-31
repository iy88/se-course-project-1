"""管理员审计查询（P3）：仅管理员、分页、白名单字段，不提供写/改/删入口。

app 角色对 audit_events 只有 SELECT/INSERT；本模块只读。保留期限未决定，
不实现定时清理。
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, or_
from sqlmodel import col, func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models.audit import AuditEvent

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])

_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 20


# 分类查询与概览共用同一表达式，避免统计和明细口径不一致。
CATEGORY_PATTERNS = {
    'account': ('auth.%', 'user.%'),
    'product': ('product.%', 'admin.product%'),
    'trade': ('trade.%', 'admin.trade%', 'system.trade%'),
    'message': ('im.%', 'conversation.%'),
    'governance': ('report.%', 'case.%', 'admin.case%', 'admin.report%', 'admin.user%'),
    'file': ('file.%',),
    'configuration': ('category.%', 'admin.category%', 'prohibited.%', 'admin.prohibited%'),
}


def _category_expression():
    return case(*[(or_(*[col(AuditEvent.event_type).like(pattern) for pattern in patterns]), name)
                  for name, patterns in CATEGORY_PATTERNS.items()], else_='other')


@router.get('/summary')
async def audit_summary(admin: CurrentAdmin, db: DbSession, days: int = Query(default=7, ge=1, le=30)) -> dict:
    """北京时间范围内数据库分组聚合；仅返回计数。"""
    zone = ZoneInfo('Asia/Shanghai')
    today = datetime.now(zone).date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    category = _category_expression()
    if db.get_bind().dialect.name == 'postgresql':
        day = func.to_char(func.timezone('Asia/Shanghai', AuditEvent.created_at), 'YYYY-MM-DD')
    else:
        day = func.date(AuditEvent.created_at, '+8 hours')
    grouped = (await db.exec(select(day, category, AuditEvent.result, func.count()).where(
        col(AuditEvent.created_at) >= start, col(AuditEvent.created_at) < end,
    ).group_by(day, category, AuditEvent.result))).all()
    categories = {name: 0 for name in (*CATEGORY_PATTERNS, 'other')}
    daily = {(today - timedelta(days=days - 1 - i)).isoformat(): 0 for i in range(days)}
    results = {'success': 0, 'failure': 0, 'denied': 0}
    for date, name, result, count in grouped:
        categories[name] += count
        daily[str(date)] += count
        results[result] = results.get(result, 0) + count
    return {'days': days, 'timezone': 'Asia/Shanghai', 'from': start.isoformat(), 'to': end.isoformat(),
            'total': sum(categories.values()), 'results': results,
            'categories': [{'category': name, 'count': count} for name, count in categories.items()],
            'daily': [{'date': date, 'count': count} for date, count in daily.items()]}


def _parse_datetime(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "时间参数须为 ISO 8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end_of_day and len(value.strip()) <= 10:
        parsed = datetime.combine(parsed.date(), time.max, tzinfo=UTC)
    return parsed.astimezone(UTC)


def _event_out(event: AuditEvent) -> dict:
    """白名单输出；before/after 在写入时已脱敏。"""
    return {
        "event_id": event.event_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "request_id": event.request_id,
        "actor_id": event.actor_id,
        "actor_role": event.actor_role,
        "event_type": event.event_type,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "result": event.result,
        "reason_code": event.reason_code,
        "before_json": event.before_json,
        "after_json": event.after_json,
        "ip": event.ip,
        "user_agent": event.user_agent,
    }


def _filters(
    *,
    event_type: str | None,
    actor_id: int | None,
    target_type: str | None,
    target_id: str | None,
    result: str | None,
    request_id: str | None,
    start: datetime | None,
    end: datetime | None,
) -> list:
    conditions = []
    if event_type:
        conditions.append(col(AuditEvent.event_type) == event_type)
    if actor_id is not None:
        conditions.append(col(AuditEvent.actor_id) == actor_id)
    if target_type:
        conditions.append(col(AuditEvent.target_type) == target_type)
    if target_id:
        conditions.append(col(AuditEvent.target_id) == target_id)
    if result:
        conditions.append(col(AuditEvent.result) == result)
    if request_id:
        conditions.append(col(AuditEvent.request_id) == request_id)
    if start is not None:
        conditions.append(col(AuditEvent.created_at) >= start)
    if end is not None:
        conditions.append(col(AuditEvent.created_at) <= end)
    return conditions


@router.get("/events")
async def list_audit_events(
    admin: CurrentAdmin,
    db: DbSession,
    event_type: Annotated[str | None, Query(max_length=64)] = None,
    category: Annotated[str | None, Query(pattern='^(account|product|trade|message|governance|file|configuration|other)$')] = None,
    actor_id: Annotated[int | None, Query(ge=1)] = None,
    target_type: Annotated[str | None, Query(max_length=32)] = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    result: Annotated[str | None, Query(pattern="^(success|failure|denied)$")] = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> dict:
    """管理员分页查询审计事件；普通用户/匿名不可访问。"""
    start = _parse_datetime(date_from)
    end = _parse_datetime(date_to, end_of_day=True)
    conditions = _filters(
        event_type=event_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        result=result,
        request_id=request_id,
        start=start,
        end=end,
    )

    if category:
        conditions.append(_category_expression() == category)

    total = int(
        (await db.exec(select(func.count()).select_from(AuditEvent).where(*conditions))).first()
        or 0
    )
    rows = (
        await db.exec(
            select(AuditEvent)
            .where(*conditions)
            .order_by(col(AuditEvent.created_at).desc(), col(AuditEvent.event_id).desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {
        "items": [_event_out(event) for event in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/events/{event_id}")
async def get_audit_event(event_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    event = await db.get(AuditEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审计事件不存在")
    return _event_out(event)
