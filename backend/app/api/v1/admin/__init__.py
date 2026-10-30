"""管理端路由汇总（全部要求管理员身份）。"""

from fastapi import APIRouter

from app.api.v1.admin import (
    case_conversations,
    cases,
    products,
    reports,
    stats,
    trades,
    users,
)

admin_router = APIRouter()
admin_router.include_router(cases.router)
admin_router.include_router(case_conversations.router)
admin_router.include_router(products.router)
admin_router.include_router(reports.router)
admin_router.include_router(trades.router)
admin_router.include_router(users.router)
admin_router.include_router(stats.router)
