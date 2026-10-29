"""禁发范围（C-16）：登录用户发布前查看；仅管理员维护（BR-13/22）。"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, CurrentUser, DbSession

router = APIRouter(prefix="/prohibited-items", tags=["prohibited-items"])


class ProhibitedItemIn(BaseModel):
    group_name: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=500)
    sort: int = 0


class ProhibitedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_name: str
    content: str
    sort: int


@router.get("", response_model=list[ProhibitedItemOut])
async def list_items(db: DbSession, user: CurrentUser) -> list[ProhibitedItemOut]:
    """已登录用户可独立查看当前禁发范围，不以已提交商品为前提（US-02-AC-08）。"""
    from app.models import ProhibitedItem

    result = await db.execute(select(ProhibitedItem).order_by(ProhibitedItem.sort, ProhibitedItem.id))
    return [ProhibitedItemOut.model_validate(i) for i in result.scalars()]


@router.post("", response_model=ProhibitedItemOut)
async def create_item(body: ProhibitedItemIn, admin: CurrentAdmin, db: DbSession) -> ProhibitedItemOut:
    from app.models import ProhibitedItem

    item = ProhibitedItem(**body.model_dump(), updated_by_id=admin.id)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ProhibitedItemOut.model_validate(item)


@router.put("/{item_id}", response_model=ProhibitedItemOut)
async def update_item(item_id: int, body: ProhibitedItemIn, admin: CurrentAdmin, db: DbSession) -> ProhibitedItemOut:
    from app.models import ProhibitedItem

    item = await db.get(ProhibitedItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "条目不存在")
    for field in ("group_name", "content", "sort"):
        setattr(item, field, getattr(body, field))
    item.updated_by_id = admin.id
    await db.commit()
    await db.refresh(item)
    return ProhibitedItemOut.model_validate(item)


@router.delete("/{item_id}")
async def delete_item(item_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    from app.models import ProhibitedItem

    item = await db.get(ProhibitedItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "条目不存在")
    await db.delete(item)
    await db.commit()
    return {"detail": "已删除"}
