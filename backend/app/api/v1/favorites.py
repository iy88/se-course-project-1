"""收藏（C-05/BR-16）：本人清单、失效提示、取消收藏。"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.models import Favorite, Product, User
from app.models.enums import ProductStatus
from app.services import audit as audit_service
from app.services.products import is_favorite_valid
from app.storage.base import get_storage

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("")
async def my_favorites(user: CurrentUser, db: DbSession) -> list[dict]:
    """本人清单；失效项仅显示通用提示，不泄露不可见内容（BR-16）。"""
    result = await db.exec(
        select(Favorite).where(col(Favorite.user_id) == user.id).order_by(col(Favorite.created_at).desc())
    )
    favorites = list(result)
    storage = get_storage()
    out: list[dict] = []
    for favorite in favorites:
        product = await db.get(Product, favorite.product_id)
        # D-44：只按当前公开资格判定；不复用买方历史详情资格，失效不硬删除收藏关系
        valid = product is not None and is_favorite_valid(product)
        if valid and product is not None:
            seller = await db.get(User, product.seller_id)
            out.append(
                {
                    "favorite_id": favorite.id,
                    "product_id": product.id,
                    "valid": True,
                    "title": product.title,
                    "price_cents": product.price_cents,
                    "image_url": storage.public_url(product.images[0].file_key) if product.images else None,
                    "tag_names": [t.name for t in product.tags],
                    "status": product.status,
                    "seller_name": seller.display_name if seller else "",
                }
            )
        else:
            out.append(
                {
                    "favorite_id": favorite.id,
                    "product_id": favorite.product_id,
                    "valid": False,
                    "title": None,
                    "price_cents": None,
                    "image_url": None,
                    "tag_names": [],
                    "status": None,
                    "seller_name": "",
                }
            )
    return out


@router.post("/{product_id}")
async def add_favorite(product_id: int, user: CurrentUser, db: DbSession) -> dict:
    """收藏公开商品；重复收藏返回已有结果（重试一致，6.5）。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.status != ProductStatus.LISTED.value or product.display_restricted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可收藏")
    exists = (await db.exec(
        select(Favorite).where(col(Favorite.user_id) == user.id, col(Favorite.product_id) == product_id)
    )).first()
    if exists:
        return {"detail": "已收藏", "favorite_id": exists.id}
    favorite = Favorite(user_id=user.id, product_id=product_id)
    db.add(favorite)
    await db.flush()
    await audit_service.record_event(
        db,
        "favorite.add",
        target_type="favorite",
        target_id=favorite.id,
        after={"product_id": product_id},
    )
    await db.commit()
    return {"detail": "已收藏", "favorite_id": favorite.id}


@router.delete("/{product_id}")
async def remove_favorite(product_id: int, user: CurrentUser, db: DbSession) -> dict:
    """取消本人收藏；失效商品仍可取消而不开放内容（BR-16）。"""
    ensure_can_write(user)
    favorite = (await db.exec(
        select(Favorite).where(col(Favorite.user_id) == user.id, col(Favorite.product_id) == product_id)
    )).first()
    if not favorite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未收藏该商品")
    favorite_id = favorite.id
    await db.delete(favorite)
    await audit_service.record_event(
        db,
        "favorite.remove",
        target_type="favorite",
        target_id=favorite_id,
        after={"product_id": product_id, "removed": True},
    )
    await db.commit()
    return {"detail": "已取消收藏"}
