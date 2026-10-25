"""API v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import auth, categories, comments, favorites, files, products, prohibited, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(files.router)
api_router.include_router(categories.router)
api_router.include_router(prohibited.router)
api_router.include_router(products.router)
api_router.include_router(favorites.router)
api_router.include_router(comments.router)
api_router.include_router(users.router)
