"""管理员账户管理：列表、封禁与解除（BR-32、DT-03、TR-10）。"""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import and_, col, func, or_, select

from app.api.deps import CurrentAdmin, DbSession
from app.models import AccountRestriction, User
from app.models.enums import AccountStatus, CaseType
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services import moderation

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class BanIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class UnbanIn(BaseModel):
    lift_reason: str = Field(min_length=1, max_length=500)


@router.get("")
async def list_users(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_status: str = Query(default="all", alias="status", pattern="^(normal|banned|all)$"),
    keyword: str | None = Query(default=None, max_length=100),
) -> dict:
    conditions = []
    if user_status != "all":
        conditions.append(col(User.status) == user_status)
    if keyword:
        like = f"%{keyword}%"
        conditions.append(or_(col(User.email).like(like), col(User.display_name).like(like)))
    count_stmt = select(func.count()).select_from(User)
    rows_stmt = select(User).order_by(col(User.id).desc())
    if conditions:
        where_clause = and_(*conditions)
        count_stmt = count_stmt.where(where_clause)
        rows_stmt = rows_stmt.where(where_clause)
    total = (await db.exec(count_stmt)).first() or 0
    query = rows_stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.exec(query)
    items = []
    for user in result:
        active_restriction = (await db.exec(
            select(AccountRestriction).where(
                col(AccountRestriction.user_id) == user.id, col(AccountRestriction.status) == "active"
            )
        )).first()
        items.append(
            {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role,
                "status": user.status,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "ban_reason": active_restriction.reason if active_restriction else None,
                "ban_at": active_restriction.created_at.isoformat() if active_restriction and active_restriction.created_at else None,
            }
        )
    return {"items": items, "total": int(total), "page": page, "page_size": page_size}


@router.post("/{user_id}/ban")
async def ban_user(user_id: int, body: BanIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """封禁账户：记录执行者、理由与时间（BR-32）；联动冻结交易与商品停止展示（DT-03）。"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能封禁管理员账户")
    if user.status == AccountStatus.BANNED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该账户已被封禁")
    # 直接触发封禁时建立封禁事项，作为申辩沟通入口；处置即时形成，
    # 执行管理员即该事项认领人（BR-34），申辩沟通限受限用户与认领管理员（BR-32）
    case = await case_service.create_case(
        db,
        case_type=CaseType.ACCOUNT_BAN,
        title=f"账户封禁：{user.display_name}（{user.email}）",
        subject_user_id=user.id,
    )
    case.claimed_by_id = admin.id
    case.claimed_at = case_service.now_utc()
    await moderation.ban_user(
        db, user, reason=body.reason.strip(), basis=None, case_id=case.id, admin_id=admin.id
    )
    await case_service.dispose_case(
        db, case, conclusion="账户封禁", reason=body.reason.strip(), basis="管理员直接处置"
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_ACCOUNT_BAN,
        target_type="user",
        target_id=user.id,
        before={"status": AccountStatus.NORMAL.value},
        after={"status": user.status, "case_id": case.id},
    )
    await db.commit()
    return {"detail": "账户已封禁，已通知本人并开通处置沟通", "case_id": case.id}


@router.post("/{user_id}/unban")
async def unban_user(user_id: int, body: UnbanIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """解除封禁：管理员确认解除后自动恢复原权限及因处置停止的展示（TR-10）。"""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.status != AccountStatus.BANNED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该账户未被封禁")
    count = await moderation.unban_user(
        db, user, lift_reason=body.lift_reason.strip(), case_id=None, admin_id=admin.id
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_ACCOUNT_UNBAN,
        target_type="user",
        target_id=user.id,
        before={"status": AccountStatus.BANNED.value},
        after={"status": user.status, "lifted_restrictions": count},
    )
    await db.commit()
    return {"detail": f"已解除 {count} 条封禁限制，原权限与展示资格已恢复"}


@router.get("/{user_id}/restrictions")
async def restriction_history(user_id: int, admin: CurrentAdmin, db: DbSession) -> list[dict]:
    result = await db.exec(
        select(AccountRestriction).where(col(AccountRestriction.user_id) == user_id).order_by(col(AccountRestriction.id))
    )
    return [
        {
            "id": r.id,
            "type": r.type,
            "status": r.status,
            "reason": r.reason,
            "basis": r.basis,
            "case_id": r.case_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "lifted_at": r.lifted_at.isoformat() if r.lifted_at else None,
            "lift_reason": r.lift_reason,
        }
        for r in result
    ]
