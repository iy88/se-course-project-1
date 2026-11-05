"""头像提交与管理员审核。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.core.text import Text500
from app.api.deps import CurrentAdmin, CurrentUser, DbSession
from app.models import DisposalCase, User
from app.models.enums import CaseStatus, CaseType
from app.models.upload_lease import UploadLease
from app.services import audit, stored_objects
from app.services.cases import create_case, dispose_case, ensure_claimant

router = APIRouter(tags=['avatars'])

class AvatarIn(BaseModel):
    key: str = Field(min_length=1, max_length=512)

class DecisionIn(BaseModel):
    key: str
    approved: bool
    reason: Text500 = Field(default='')

@router.post('/auth/avatar')
async def submit_avatar(body: AvatarIn, user: CurrentUser, db: DbSession):
    return await submit_avatar_transaction(body, user, db, commit=True)


async def submit_avatar_transaction(body: AvatarIn, user: User, db, *, commit: bool):
    if user.status != 'normal':
        raise HTTPException(403, '当前账户状态无法提交头像')
    # 锁定账户，与审核串行；始终要求已完成且属于本人的头像租约。
    user = (await db.exec(select(User).where(col(User.id) == user.id).with_for_update().execution_options(populate_existing=True))).one()
    lease = (await db.exec(select(UploadLease).where(col(UploadLease.key) == body.key))).one_or_none()
    if not lease or lease.owner_id != user.id or lease.namespace != 'avatar' or lease.state != 'completed':
        raise HTTPException(400, '请上传并验证本人的头像图片')
    if user.avatar_review_status == 'pending':
        if user.avatar_pending_key == body.key:
            existing = (await db.exec(select(DisposalCase).where(
                col(DisposalCase.subject_user_id) == user.id,
                col(DisposalCase.case_type) == CaseType.AVATAR_REVIEW.value,
                col(DisposalCase.avatar_key) == body.key,
                col(DisposalCase.status).in_([CaseStatus.PENDING.value, CaseStatus.PROCESSING.value]),
            ))).one_or_none()
            if existing:
                return {'detail': '头像已提交审核', 'case_id': existing.id}
        raise HTTPException(409, '头像正在审核，请等待审核结果')
    await stored_objects.mark_committed(db, [body.key], ref_type='avatar', ref_id=user.id)
    user.avatar_pending_key = body.key
    user.avatar_review_status = 'pending'
    user.avatar_review_reason = None
    case = await create_case(db, case_type=CaseType.AVATAR_REVIEW, title=f'头像审核：{user.display_name}', subject_user_id=user.id)
    case.avatar_key = body.key
    await audit.record_event(db, 'user.avatar_submit', target_type='user', target_id=user.id, actor_id=user.id, actor_role=user.role)
    if commit:
        await db.commit()
    return {'detail': '头像已提交审核', 'case_id': case.id}

@router.post('/admin/cases/{case_id}/avatar-decision')
async def decide_avatar(case_id: int, body: DecisionIn, admin: CurrentAdmin, db: DbSession):
    case = (await db.exec(select(DisposalCase).where(col(DisposalCase.id) == case_id).with_for_update().execution_options(populate_existing=True))).one_or_none()
    if not case or case.case_type != CaseType.AVATAR_REVIEW.value:
        raise HTTPException(404, '头像审核事项不存在')
    await ensure_claimant(case, admin.id)
    if case.status != CaseStatus.PROCESSING.value:
        raise HTTPException(409, '事项已处理，请刷新')
    user_id = case.subject_user_id
    if not body.approved and not body.reason.strip():
        raise HTTPException(422, '请填写拒绝原因')
    user = (await db.exec(select(User).where(col(User.id) == user_id).with_for_update().execution_options(populate_existing=True))).one_or_none()
    if not user:
        raise HTTPException(404, '用户不存在')
    if user.avatar_review_status != 'pending' or user.avatar_pending_key != body.key or case.avatar_key != body.key:
        raise HTTPException(409, '头像申请已处理或已更新，请刷新列表')
    if body.approved:
        user.avatar_key = user.avatar_pending_key
    user.avatar_review_status = 'approved' if body.approved else 'rejected'
    user.avatar_review_reason = body.reason.strip() or None
    user.avatar_pending_key = None
    await dispose_case(db, case, conclusion='approved' if body.approved else 'rejected', reason=body.reason.strip() or None)
    await audit.record_event(db, 'user.avatar_review', target_type='user', target_id=user.id, actor_id=admin.id, actor_role=admin.role, after={'approved': body.approved}, reason_code='approved' if body.approved else 'rejected')
    await db.commit()
    return {'detail': '头像审核完成'}
