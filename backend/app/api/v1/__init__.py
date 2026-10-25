"""API v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import auth, categories, files, prohibited

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(files.router)
api_router.include_router(categories.router)
api_router.include_router(prohibited.router)
