"""测试夹具：独立 SQLite 测试库、内存 KV、临时本地存储、ASGI 客户端。"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.session import Base, get_db
from app.models import User

TEST_IMAGE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082"
)


@pytest_asyncio.fixture
async def db(tmp_path):
    """独立测试库会话（与请求会话同库，供直接断言/构造数据）。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionMaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionMaker() as session:
        admin = User(
            email="admin@test.edu",
            display_name="测试管理员",
            password_hash=hash_password("admin123456"),
            role="admin",
        )
        session.add(admin)
        from app.models import Category

        session.add_all([Category(name=name, created_by_id=1) for name in ["教材书籍", "电子产品", "生活用品", "运动器材"]])
        await session.commit()
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(tmp_path, db):
    test_engine = None
    # 复用 db 夹具的数据库文件：通过其 bind 创建请求会话工厂
    bind = db.bind
    SessionMaker = async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with SessionMaker() as session:
            yield session

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db

    import app.kv.base as kv_base
    import app.storage.base as storage_base

    kv_base._kv = kv_base.MemoryKV()
    storage_base._storage = storage_base.LocalStorage(tmp_path / "storage")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


async def make_admin(db: AsyncSession, email: str = "admin@test.edu") -> User:
    """幂等创建/复用测试管理员。"""
    from sqlalchemy import select

    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        return existing
    user = User(email=email, display_name="测试管理员", password_hash=hash_password("admin123456"), role="admin")
    db.add(user)
    await db.commit()
    return user


async def register(client, email: str, name: str = "用户", password: str = "secret123") -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def login(client, email: str, password: str = "secret123") -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def user_headers(client, email: str, name: str = "用户") -> dict:
    await register(client, email, name)
    return {"Authorization": f"Bearer {await login(client, email)}"}


async def admin_headers(client, email: str = "admin@test.edu") -> dict:
    return {"Authorization": f"Bearer {await login(client, email, 'admin123456')}"}


async def upload_image(client, headers: dict) -> str:
    resp = await client.post(
        "/api/v1/files/upload?namespace=product",
        headers=headers,
        files={"file": ("test.png", TEST_IMAGE_PNG, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["key"]


async def publish_product(client, headers: dict, title: str = "测试商品", price_cents: int = 1000, category_id: int | None = 1) -> dict:
    resp = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "title": title,
            "description": "测试描述，九成新",
            "price_cents": price_cents,
            "image_keys": [await upload_image(client, headers)],
            "tags": [{"category_id": category_id}] if category_id else [{"new_name": "测试新标签"}],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def approve_product(client, admin: dict, product_id: int) -> None:
    """管理员认领首个待审事项并通过（含标签申请默认批准为新标签）。"""
    resp = await client.get("/api/v1/admin/cases?status=pending", headers=admin)
    assert resp.status_code == 200, resp.text
    cases = [c for c in resp.json() if c["case_type"] == "product_review"]
    target = next(c for c in cases if c["product_id"] == product_id)
    resp = await client.post(f"/api/v1/admin/cases/{target['id']}/claim", headers=admin)
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/products/cases/{target['id']}/review",
        headers=admin,
        json={"result": "approved", "tag_decisions": []},
    )
    assert resp.status_code == 200, resp.text


async def create_listed_product(client, admin: dict, seller: dict, title: str = "测试商品", price_cents: int = 1000) -> dict:
    product = await publish_product(client, seller, title=title, price_cents=price_cents)
    await approve_product(client, admin, product["id"])
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller)
    assert resp.status_code == 200
    return resp.json()
