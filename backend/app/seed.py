"""开发种子数据：管理员、初始分类标签、禁发范围（BR-13/4.16：初始条目由管理员准备）。

用法：uv run python -m app.seed
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Category, ProhibitedItem, User

ADMIN_EMAIL = "admin@campus.edu"
ADMIN_PASSWORD = "admin123456"

INITIAL_CATEGORIES = [
    "教材书籍",
    "电子产品",
    "生活用品",
    "运动器材",
    "服饰鞋包",
    "宿舍家电",
    "美妆个护",
    "文具用品",
    "乐器",
    "其他闲置",
]

# BR-13 规定的最低禁发类别 + 示例细目
INITIAL_PROHIBITED = [
    ("法律法规禁止流通的物品", "枪支弹药、管制刀具等法律禁止流通物"),
    ("危险品与管制物品", "易燃易爆品、剧毒化学品、放射性物品"),
    ("活体动物", "各类宠物及活体动物"),
    ("药品与医疗器械", "处方药、疫苗、注射类医疗器械"),
    ("账号与虚拟财产", "游戏账号、校园账号、虚拟货币及账号租售"),
    ("无关服务或推广内容", "广告推广、代跑腿、代做作业等与二手闲置无关内容"),
]


async def seed() -> None:
    from app.db.session import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin is None:
            admin = User(
                email=ADMIN_EMAIL,
                display_name="平台管理员",
                password_hash=hash_password(ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin)
            await db.flush()
            print(f"已创建管理员 {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            print("管理员已存在，跳过")

        for name in INITIAL_CATEGORIES:
            exists = await db.scalar(select(Category).where(Category.name == name, Category.deleted_at.is_(None)))
            if not exists:
                db.add(Category(name=name, created_by_id=admin.id))
        print(f"初始分类标签：{len(INITIAL_CATEGORIES)} 项（已存在跳过）")

        count = await db.scalar(select(User.id).limit(1))
        if count:
            prohibited_count = 0
            for group, content in INITIAL_PROHIBITED:
                exists = await db.scalar(
                    select(ProhibitedItem).where(ProhibitedItem.group_name == group, ProhibitedItem.content == content)
                )
                if not exists:
                    db.add(ProhibitedItem(group_name=group, content=content, updated_by_id=admin.id))
                    prohibited_count += 1
            await db.commit()
            print(f"禁发范围条目新增：{prohibited_count} 项")
            return
        await db.commit()
        print("种子数据完成")


if __name__ == "__main__":
    asyncio.run(seed())
