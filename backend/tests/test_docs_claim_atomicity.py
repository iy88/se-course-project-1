"""并发原子性回归：认领与撤回审核对同一事项的数据库条件竞争（BR-34/D-46/TR-20）。

使用实际临时 SQLite 文件库，每个并发请求持有独立 AsyncSession；先读取同一
pending 状态制造交错，再由数据库条件 UPDATE 决定唯一胜者。不依赖同一 session
内 gather，也不 mock 掉数据库判定。
"""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.storage.base as storage_base
from app.api.v1 import products as products_api
from app.api.v1.admin import cases as admin_cases
from app.db.session import Base
from app.models import (
    DisposalCase,
    DisposalMessage,
    Product,
    ProductTagApplication,
    ReviewRecord,
    User,
)
from app.models.enums import CaseStatus, CaseType, ProductStatus, ReviewResult
from app.storage.base import LocalStorage

pytestmark = pytest.mark.asyncio

_ADMIN1 = "race-admin1@test.edu"
_ADMIN2 = "race-admin2@test.edu"
_SELLER = "race-seller@test.edu"
_WORKER_TIMEOUT = 15
_BARRIER_TIMEOUT = 5


@pytest.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/claim-race.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        session.add_all(
            [
                User(email=_ADMIN1, display_name="管理员一", password_hash="unused", role="admin"),
                User(email=_ADMIN2, display_name="管理员二", password_hash="unused", role="admin"),
                User(email=_SELLER, display_name="卖方", password_hash="unused", role="user"),
            ]
        )
        await session.commit()
    previous_storage = storage_base._storage
    storage_base._storage = LocalStorage(tmp_path / "storage")
    try:
        yield {"Session": Session}
    finally:
        storage_base._storage = previous_storage
        await engine.dispose()


async def _seed_pending_review(Session) -> dict:
    async with Session() as session:
        seller = await session.scalar(select(User).where(User.email == _SELLER))
        product = Product(
            seller_id=seller.id,
            title="并发审核商品",
            description="并发测试描述",
            price_cents=1200,
            status=ProductStatus.PENDING_REVIEW.value,
        )
        session.add(product)
        await session.flush()
        case = DisposalCase(
            case_type=CaseType.PRODUCT_REVIEW.value,
            status=CaseStatus.PENDING.value,
            title=f"商品审核：{product.title}",
            subject_user_id=seller.id,
            product_id=product.id,
        )
        session.add(case)
        await session.flush()
        review = ReviewRecord(
            product_id=product.id,
            content_json={"title": product.title},
            result=ReviewResult.PENDING.value,
            case_id=case.id,
        )
        application = ProductTagApplication(product_id=product.id, requested_name="并发标签", status="pending")
        session.add_all([review, application])
        await session.commit()
        return {
            "product_id": product.id,
            "case_id": case.id,
            "review_id": review.id,
            "application_id": application.id,
        }


async def _user(session, email: str) -> User:
    return await session.scalar(select(User).where(User.email == email))


async def _claim_worker(
    env,
    ids: dict,
    email: str,
    *,
    read_first: bool = False,
    read_event: asyncio.Event | None = None,
    wait_event: asyncio.Event | None = None,
    barrier: asyncio.Barrier | None = None,
) -> dict:
    """独立会话调用认领；可在初始读取后等待事件/屏障，制造真实交错。"""
    async with env["Session"]() as session:
        user = await _user(session, email)
        admin_id = user.id
        try:
            if read_first:
                observed = await session.scalar(
                    select(DisposalCase.status).where(DisposalCase.id == ids["case_id"])
                )
                assert observed == CaseStatus.PENDING.value, observed
                if read_event is not None:
                    read_event.set()
            if wait_event is not None:
                await asyncio.wait_for(wait_event.wait(), _BARRIER_TIMEOUT)
            if barrier is not None:
                await asyncio.wait_for(barrier.wait(), _BARRIER_TIMEOUT)
            result = await admin_cases.claim_case(ids["case_id"], user, session)
            return {
                "role": "claim",
                "admin_id": admin_id,
                "status": 200,
                "detail": result.detail,
            }
        except HTTPException as exc:
            return {"role": "claim", "admin_id": admin_id, "status": exc.status_code, "detail": exc.detail}
        except Exception as exc:  # noqa: BLE001 - 回归必须暴露非预期异常而非挂起
            return {
                "role": "claim",
                "admin_id": admin_id,
                "status": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }


async def _withdraw_worker(env, ids: dict) -> dict:
    """独立会话调用撤回审核。"""
    async with env["Session"]() as session:
        seller = await _user(session, _SELLER)
        seller_id = seller.id
        try:
            product_out = await products_api.withdraw_review(ids["product_id"], seller, session)
            return {
                "role": "withdraw",
                "seller_id": seller_id,
                "status": 200,
                "product_status": product_out.status.value,
                "can_resubmit": product_out.can_resubmit,
                "detail": "撤回成功",
            }
        except HTTPException as exc:
            return {"role": "withdraw", "seller_id": seller_id, "status": exc.status_code, "detail": exc.detail}
        except Exception as exc:  # noqa: BLE001 - 回归必须暴露非预期异常而非挂起
            return {
                "role": "withdraw",
                "seller_id": seller_id,
                "status": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }


async def _db_state(env, ids: dict) -> dict:
    async with env["Session"]() as session:
        case = await session.get(DisposalCase, ids["case_id"])
        product = await session.get(Product, ids["product_id"])
        review = await session.get(ReviewRecord, ids["review_id"])
        application = await session.get(ProductTagApplication, ids["application_id"])
        messages = (
            (
                await session.execute(
                    select(DisposalMessage)
                    .where(DisposalMessage.case_id == ids["case_id"])
                    .order_by(DisposalMessage.id)
                )
            )
            .scalars()
            .all()
        )
        case_count = await session.scalar(
            select(func.count()).select_from(DisposalCase).where(DisposalCase.product_id == ids["product_id"])
        )
        return {
            "case_status": case.status,
            "claimed_by_id": case.claimed_by_id,
            "claimed_at": case.claimed_at,
            "conclusion": case.conclusion,
            "basis": case.basis,
            "disposed_at": case.disposed_at,
            "product_status": product.status,
            "delisted_at": product.delisted_at,
            "review_result": review.result,
            "application_status": application.status,
            "messages": [(m.role, m.kind, m.content) for m in messages],
            "case_count": case_count,
        }


async def _run(*coros) -> list:
    return await asyncio.wait_for(asyncio.gather(*coros), timeout=_WORKER_TIMEOUT * 2)


async def _one(coro):
    """单个并发请求的硬超时，避免异常路径下等待不返回。"""
    return await asyncio.wait_for(coro, timeout=_WORKER_TIMEOUT)


async def test_claim_race_only_one_admin_wins_and_replay_keeps_owner(env):
    """两管理员先读同一 pending，再竞争认领：恰一人 200，另一人 409。"""
    ids = await _seed_pending_review(env["Session"])
    barrier = asyncio.Barrier(2)
    results = await _run(
        _claim_worker(env, ids, _ADMIN1, read_first=True, barrier=barrier),
        _claim_worker(env, ids, _ADMIN2, read_first=True, barrier=barrier),
    )

    winners = [r for r in results if r["status"] == 200]
    losers = [r for r in results if r["status"] == 409]
    assert len(winners) == 1 and len(losers) == 1, results
    assert winners[0]["detail"] == "认领成功"

    state = await _db_state(env, ids)
    assert state["case_status"] == CaseStatus.PROCESSING.value
    assert state["claimed_by_id"] == winners[0]["admin_id"]
    assert state["claimed_at"] is not None
    assert state["case_count"] == 1

    # 顺序重放（胜者与败者）均不得改写 owner，也不得产生第二个事项。
    for email in (_ADMIN1, _ADMIN2):
        replay = await _one(_claim_worker(env, ids, email))
        assert replay["status"] == 409, replay
    replay_state = await _db_state(env, ids)
    assert replay_state["claimed_by_id"] == winners[0]["admin_id"]
    assert replay_state["case_status"] == CaseStatus.PROCESSING.value
    assert replay_state["case_count"] == 1


async def test_withdraw_then_claim_stays_withdrawn_and_never_revives(env):
    """撤回先成功：事项 disposed、商品下架、审核/申请结束，随后认领必须 409。"""
    ids = await _seed_pending_review(env["Session"])
    withdraw = await _one(_withdraw_worker(env, ids))
    assert withdraw["status"] == 200, withdraw
    assert withdraw["product_status"] == ProductStatus.DELISTED.value
    assert withdraw["can_resubmit"] is True

    state = await _db_state(env, ids)
    assert state["case_status"] == CaseStatus.DISPOSED.value
    assert state["claimed_by_id"] is None
    assert state["conclusion"] == "卖方撤回审核"
    assert state["basis"] == "D-46"
    assert state["disposed_at"] is not None
    assert state["product_status"] == ProductStatus.DELISTED.value
    assert state["delisted_at"] is not None
    assert state["review_result"] == ReviewResult.WITHDRAWN.value
    assert state["application_status"] == "withdrawn"
    assert any(role == "system" and kind == "notice" for role, kind, _ in state["messages"])
    assert state["case_count"] == 1

    for email in (_ADMIN1, _ADMIN2):
        claim = await _one(_claim_worker(env, ids, email))
        assert claim["status"] == 409, claim

    # 撤回后不得被认领复活，也不得留下假 owner 或半成品。
    after = await _db_state(env, ids)
    assert after["case_status"] == CaseStatus.DISPOSED.value
    assert after["claimed_by_id"] is None
    assert after["product_status"] == ProductStatus.DELISTED.value
    assert after["review_result"] == ReviewResult.WITHDRAWN.value
    assert after["application_status"] == "withdrawn"
    assert after["case_count"] == 1


async def test_claim_then_withdraw_keeps_pending_content(env):
    """认领先成功：撤回 409，商品/审核/申请均保持 pending，事项唯一 owner 不变。"""
    ids = await _seed_pending_review(env["Session"])
    claim = await _one(_claim_worker(env, ids, _ADMIN1))
    assert claim["status"] == 200, claim

    withdraw = await _one(_withdraw_worker(env, ids))
    assert withdraw["status"] == 409, withdraw

    state = await _db_state(env, ids)
    assert state["case_status"] == CaseStatus.PROCESSING.value
    assert state["claimed_by_id"] == claim["admin_id"]
    assert state["product_status"] == ProductStatus.PENDING_REVIEW.value
    assert state["delisted_at"] is None
    assert state["review_result"] == ReviewResult.PENDING.value
    assert state["application_status"] == "pending"
    assert state["messages"] == []
    assert state["case_count"] == 1

    # 另一管理员及重复撤回均不得接管或改变待审内容。
    assert (await _one(_claim_worker(env, ids, _ADMIN2)))["status"] == 409
    assert (await _one(_withdraw_worker(env, ids)))["status"] == 409
    after = await _db_state(env, ids)
    assert after["claimed_by_id"] == claim["admin_id"]
    assert after["product_status"] == ProductStatus.PENDING_REVIEW.value
    assert after["review_result"] == ReviewResult.PENDING.value
    assert after["application_status"] == "pending"


async def test_withdraw_blocked_midflight_when_claim_wins(env, monkeypatch):
    """撤回已读取待审内容后暂停，认领先完成；撤回的原子更新必须失败且无副作用。"""
    ids = await _seed_pending_review(env["Session"])
    withdraw_ready = asyncio.Event()
    claim_done = asyncio.Event()
    original = products_api._dispose_review_case_atomically

    async def delayed_withdraw(db, case_id, *, now):
        withdraw_ready.set()
        await asyncio.wait_for(claim_done.wait(), _BARRIER_TIMEOUT)
        return await original(db, case_id, now=now)

    monkeypatch.setattr(products_api, "_dispose_review_case_atomically", delayed_withdraw)

    withdraw_task = asyncio.create_task(_withdraw_worker(env, ids))
    await asyncio.wait_for(withdraw_ready.wait(), _BARRIER_TIMEOUT)
    claim = await _one(_claim_worker(env, ids, _ADMIN1))
    claim_done.set()
    withdraw = await asyncio.wait_for(withdraw_task, timeout=_WORKER_TIMEOUT)

    assert claim["status"] == 200, claim
    assert withdraw["status"] == 409, withdraw
    state = await _db_state(env, ids)
    assert state["case_status"] == CaseStatus.PROCESSING.value
    assert state["claimed_by_id"] == claim["admin_id"]
    assert state["product_status"] == ProductStatus.PENDING_REVIEW.value
    assert state["delisted_at"] is None
    assert state["review_result"] == ReviewResult.PENDING.value
    assert state["application_status"] == "pending"
    assert state["messages"] == []


async def test_claim_blocked_midflight_when_withdraw_wins(env):
    """认领已读取 pending 后暂停，撤回先完成；认领的原子更新必须失败且不复活事项。"""
    ids = await _seed_pending_review(env["Session"])
    read_done = asyncio.Event()
    withdraw_done = asyncio.Event()

    claim_task = asyncio.create_task(
        _claim_worker(
            env,
            ids,
            _ADMIN1,
            read_first=True,
            read_event=read_done,
            wait_event=withdraw_done,
        )
    )
    await asyncio.wait_for(read_done.wait(), _BARRIER_TIMEOUT)
    withdraw = await _one(_withdraw_worker(env, ids))
    withdraw_done.set()
    claim = await asyncio.wait_for(claim_task, timeout=_WORKER_TIMEOUT)

    assert withdraw["status"] == 200, withdraw
    assert claim["status"] == 409, claim
    state = await _db_state(env, ids)
    assert state["case_status"] == CaseStatus.DISPOSED.value
    assert state["claimed_by_id"] is None
    assert state["product_status"] == ProductStatus.DELISTED.value
    assert state["review_result"] == ReviewResult.WITHDRAWN.value
    assert state["application_status"] == "withdrawn"
    assert any(role == "system" and kind == "notice" for role, kind, _ in state["messages"])


async def test_simultaneous_withdraw_and_claim_have_single_winner(env, monkeypatch):
    """双方向同时到达数据库条件更新：仅一个成功，数据库后果与胜者完全一致。"""
    ids = await _seed_pending_review(env["Session"])
    barrier = asyncio.Barrier(2)
    original_withdraw = products_api._dispose_review_case_atomically
    original_claim = admin_cases._claim_pending_case

    async def delayed_withdraw(db, case_id, *, now):
        await asyncio.wait_for(barrier.wait(), _BARRIER_TIMEOUT)
        return await original_withdraw(db, case_id, now=now)

    async def delayed_claim(db, case_id, admin_id, claimed_at):
        await asyncio.wait_for(barrier.wait(), _BARRIER_TIMEOUT)
        return await original_claim(db, case_id, admin_id, claimed_at)

    monkeypatch.setattr(products_api, "_dispose_review_case_atomically", delayed_withdraw)
    monkeypatch.setattr(admin_cases, "_claim_pending_case", delayed_claim)

    results = await _run(
        _withdraw_worker(env, ids),
        _claim_worker(env, ids, _ADMIN2),
    )
    winners = [r for r in results if r["status"] == 200]
    assert len(winners) == 1, results
    assert sorted(r["status"] for r in results) == [200, 409], results

    state = await _db_state(env, ids)
    if winners[0]["role"] == "claim":
        assert state["case_status"] == CaseStatus.PROCESSING.value
        assert state["claimed_by_id"] == winners[0]["admin_id"]
        assert state["product_status"] == ProductStatus.PENDING_REVIEW.value
        assert state["review_result"] == ReviewResult.PENDING.value
        assert state["application_status"] == "pending"
        assert state["messages"] == []
    else:
        assert state["case_status"] == CaseStatus.DISPOSED.value
        assert state["claimed_by_id"] is None
        assert state["product_status"] == ProductStatus.DELISTED.value
        assert state["review_result"] == ReviewResult.WITHDRAWN.value
        assert state["application_status"] == "withdrawn"
        assert any(role == "system" and kind == "notice" for role, kind, _ in state["messages"])
    assert state["case_count"] == 1
