"""Public (signed-in only) user information such as seller profiles."""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, DbSession
from app.models import Product, User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/profile")
async def user_profile(user_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Seller profile: display name and listed products, serving as the entry point for starting a regular private chat (FR-04)."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    result = await db.exec(
        select(Product).where(
            col(Product.seller_id) == user_id,
            col(Product.status) == "listed",
            col(Product.display_restricted).is_(False),
        ).order_by(col(Product.created_at).desc())
    )
    products = list(result)
    from app.storage.base import get_storage

    storage = get_storage()
    return {
        "id": target.id,
        "display_name": target.display_name,
        "avatar_url": storage.public_url(target.avatar_key) if target.avatar_key else None,
        "is_self": target.id == user.id,
        "products": [
            {
                "id": p.id,
                "title": p.title,
                "price_cents": p.price_cents,
                "image_url": storage.public_url(p.images[0].file_key) if p.images else None,
            }
            for p in products
        ],
    }
