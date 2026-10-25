"""API v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    categories,
    comments,
    conversations,
    favorites,
    files,
    my_cases,
    notifications,
    products,
    prohibited,
    reports,
    reviews,
    trades,
    users,
)
from app.api.v1.admin import admin_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(files.router)
api_router.include_router(categories.router)
api_router.include_router(prohibited.router)
api_router.include_router(products.router)
api_router.include_router(favorites.router)
api_router.include_router(comments.router)
api_router.include_router(users.router)
api_router.include_router(conversations.router)
api_router.include_router(trades.router)
api_router.include_router(reviews.router)
api_router.include_router(reviews.reviews_router)
api_router.include_router(reports.router)
api_router.include_router(my_cases.router)
api_router.include_router(notifications.router)
api_router.include_router(admin_router)
