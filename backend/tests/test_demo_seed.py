"""持久 demo-seed 的 SQLite/local 回归：真实记录、状态转换、拒绝与幂等。"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.admin.cases import case_detail, claim_case
from app.api.v1.admin.products import (
    ReviewDecisionIn,
    TagDecisionIn,
    review_product,
    restore_product_display,
    RestoreDisplayIn,
)
from app.api.v1.admin.reports import ReportDecisionIn, decide_report
from app.api.v1.admin.users import UnbanIn, unban_user
from app.api.v1.categories import delete_category, update_category
from app.api.v1.favorites import add_favorite, my_favorites
from app.api.v1.my_cases import submit_appeal
from app.api.v1.conversations import advance_read, send_message
from app.api.v1.notifications import list_todos, mark_read
from app.api.v1.products import detail, restriction_result, search, withdraw_review, resubmit
from app.api.v1.reports import ReportCreateIn, SupplementIn, add_supplement, create_report, my_reports
from app.api.v1.trades import (
    accept_request,
    confirm_agreement,
    confirm_cancel,
    create_request,
    propose_cancel,
    reject_agreement,
    resolve_dispute,
    submit_confirmation,
    trade_detail,
    withdraw_cancel,
)
from app.api.v1.admin.cases import CaseMessageIn, admin_reply
from app.api.v1.admin.trades import AdjustIn, UnfreezeIn, adjust_status, unfreeze
from app.core.private_files import require_private
from app.core.security import verify_password
from app.db.session import Base
from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.verify import verify
from app.models import User
from app.models.category import Category, CategoryAlias
from app.models.governance import Notification, Report
from app.models.im import Conversation, ConversationRead, Message
from app.models.product import Product, ProductTagApplication, ReviewRecord
from app.models.trade import CompletionConfirmation, Trade, TradeAgreement
from app.schemas.conversation import MessageIn, ReadAdvanceIn
from app.schemas.trade import (
    AgreementProposeIn,
    CancelIn,
    ConfirmationIn,
    RequestCreateIn,
)
from app.services import trade_timeout


def _write_env(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    db_path = tmp_path / 'demo.db'
    storage = tmp_path / 'storage'
    manifest = tmp_path / 'manifest.json'
    env_file = tmp_path / 'demo.env'
    env_file.write_text(f'''APP_NAME=DemoTest
ENVIRONMENT=test
DATABASE_URL=sqlite+aiosqlite:///{db_path}
DATABASE_SCHEMA=app
DB_AUTO_CREATE=false
AUDIT_TRUSTED_PROXIES=none
STORAGE_LOCAL_ROOT={storage}
JWT_SECRET=abcdefghijklmnopqrstuvwxyz1234567890
JWT_ALGORITHM=HS256
FILE_URL_SECRET=anotherabcdefghijklmnopqrstuvwxyz1234567890
SMTP_SECURITY=ssl
SMTP_HOST=mail.example.org
SMTP_USERNAME=testuser
SMTP_PASSWORD=testingpassword
SMTP_FROM_EMAIL=test@example.org
SMTP_FROM_NAME=Demo
''')
    return env_file, f'sqlite+aiosqlite:///{db_path}', storage, manifest


def _create_schema(url: str, *, existing: bool = True) -> None:
    async def run():
        engine = create_async_engine(url)
        @event.listens_for(engine.sync_engine, 'connect')
        def foreign_keys(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        if existing:
            async with AsyncSession(engine) as session:
                session.add(User(email='existing@example.org', password_hash='original-hash', display_name='Existing'))
                await session.commit()
        await engine.dispose()
    asyncio.run(run())


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(('APP_ENV_', 'DATABASE_', 'STORAGE_', 'OSS_', 'JWT_', 'FILE_URL_'))}


def _run(env_file: Path, manifest: Path, *, fault: bool = False, response_lost: bool = False) -> subprocess.CompletedProcess:
    cwd = Path(__file__).resolve().parents[1]
    if not fault:
        return subprocess.run(
            [sys.executable, '-X', 'utf8', '-m', 'app.manage', 'demo-seed', '--env-file', str(env_file), '--manifest', str(manifest)],
            cwd=cwd, env=_clean_env(), capture_output=True, text=True, encoding='utf-8', check=False,
        )
    code = """
import sys
import app.storage.base as storage_base
from app.devtools.demo_seed import main
original_build = storage_base.build_storage
class FailingStorage:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = 0
    def __getattr__(self, name):
        return getattr(self.wrapped, name)
    def save_to_key(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 2:
            if RESPONSE_LOST:
                self.wrapped.save_to_key(*args, **kwargs)
            raise RuntimeError('injected storage failure')
        return self.wrapped.save_to_key(*args, **kwargs)
storage_base.build_storage = lambda settings: FailingStorage(original_build(settings))
raise SystemExit(main(sys.argv[1:]))
"""
    code = code.replace('RESPONSE_LOST', str(response_lost))
    return subprocess.run(
        [sys.executable, '-X', 'utf8', '-c', code, '--env-file', str(env_file), '--manifest', str(manifest)],
        cwd=cwd, env=_clean_env(), capture_output=True, text=True, encoding='utf-8', check=False,
    )


def _load_manifest(manifest: Path) -> dict:
    return json.loads(manifest.read_text(encoding='utf-8'))


def _id(data: dict, key: str) -> int:
    return int(data['objects'][key]['id'])


def _session(url: str) -> tuple:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _fresh(session: AsyncSession, model, object_id: int):
    return await session.get(model, object_id, populate_existing=True)


def test_demo_seed_sqlite_local(tmp_path):
    env_file, url, storage_root, manifest = _write_env(tmp_path)
    _create_schema(url)
    assert not manifest.exists()

    failed = _run(env_file, manifest, fault=True)
    assert failed.returncode != 0 and 'RuntimeError' in failed.stderr
    partial = _load_manifest(manifest)
    assert partial['version'] == 2 and not partial['complete']
    assert len(partial['files']) == 2
    partial_keys = {entry['key'] for entry in partial['files'].values()}
    existing_keys = {p.relative_to(storage_root).as_posix() for p in storage_root.rglob('*') if p.is_file()}
    assert len(existing_keys) == 1 and existing_keys <= partial_keys

    first = _run(env_file, manifest)
    assert first.returncode == 0, first.stderr
    data = _load_manifest(manifest)
    assert data['complete'] and data['catalog_signature'] == catalog.catalog_signature()
    assert data['scenarios'] == [scenario.key for scenario in catalog.SCENARIOS]
    assert set(data['object_kinds']) == set(data['objects'])
    require_private(manifest)
    final_keys = {entry['key'] for entry in data['files'].values()}
    assert partial_keys <= final_keys
    assert {p.relative_to(storage_root).as_posix() for p in storage_root.rglob('*') if p.is_file()} == final_keys
    assert len(data['accounts']) == len(catalog.ACCOUNTS)
    assert len(data['objects']) >= 400

    async def inspect_and_verify():
        from app.storage.base import LocalStorage
        import app.storage.base as storage_base
        storage = LocalStorage(storage_root)
        storage_base._storage = storage
        engine, factory = _session(url)
        try:
            async with factory() as session:
                violations = (await session.exec(__import__('sqlalchemy').text('PRAGMA foreign_key_check'))).all()
                assert not violations
                existing = (await session.exec(select(User).where(User.email == 'existing@example.org'))).one()
                assert (existing.display_name, existing.password_hash) == ('Existing', 'original-hash')
                for account in data['accounts'].values():
                    user = await session.get(User, account['id'])
                    assert user.email == account['email'] and user.role == account['role']
                    assert verify_password(account['password'], user.password_hash)
                report = await verify(session, storage, data, verify_api=True)
                assert report.ok(), report.errors[:10]
                assert report.checks >= 3000
                counts = {}
                for table in Base.metadata.sorted_tables:
                    counts[table.name] = (await session.exec(
                        __import__('sqlalchemy').text(f'SELECT count(*) FROM "{table.name}"')
                    )).one()[0]
                return counts
        finally:
            await engine.dispose()
    counts = asyncio.run(inspect_and_verify())

    async def inspect_counts():
        from sqlalchemy import text
        engine, factory = _session(url)
        try:
            async with factory() as session:
                result = {}
                for table in Base.metadata.sorted_tables:
                    result[table.name] = (await session.exec(text(f'SELECT count(*) FROM "{table.name}"'))).one()[0]
                return result
        finally:
            await engine.dispose()

    # 重跑幂等：人工修改必须保留，manifest 与计数不变。
    async def edit_seeded_data():
        engine, factory = _session(url)
        try:
            async with factory() as session:
                user = await session.get(User, data['accounts']['seller']['id'])
                product = await session.get(Product, _id(data, 'product_bike'))
                user.display_name = 'Edited seller'
                product.title = 'Edited listing'
                await session.commit()
        finally:
            await engine.dispose()
    asyncio.run(edit_seeded_data())
    before = manifest.read_bytes()
    second = _run(env_file, manifest)
    assert second.returncode == 0, second.stderr
    assert manifest.read_bytes() == before
    assert asyncio.run(inspect_counts()) == counts

    async def assert_edits_preserved():
        engine, factory = _session(url)
        try:
            async with factory() as session:
                user = await session.get(User, data['accounts']['seller']['id'])
                product = await session.get(Product, _id(data, 'product_bike'))
                assert (user.display_name, product.title) == ('Edited seller', 'Edited listing')
        finally:
            await engine.dispose()
    asyncio.run(assert_edits_preserved())

    # 旧版本、目录变化与目标变化都必须明确拒绝，且不写新目标。
    stale_version = dict(data)
    stale_version['version'] = 1
    manifest.write_bytes(json.dumps(stale_version, ensure_ascii=False).encode())
    refused = _run(env_file, manifest)
    assert refused.returncode != 0 and '版本' in refused.stderr
    stale_signature = dict(data)
    stale_signature['catalog_signature'] = '0' * 64
    manifest.write_bytes(json.dumps(stale_signature, ensure_ascii=False).encode())
    refused = _run(env_file, manifest)
    assert refused.returncode != 0 and '目录' in refused.stderr
    manifest.write_bytes(before)

    other_storage = tmp_path / 'other-storage'
    env_file.write_text(env_file.read_text().replace(str(storage_root), str(other_storage)))
    refused = _run(env_file, manifest)
    assert refused.returncode != 0
    assert manifest.read_bytes() == before
    assert not other_storage.exists() or not any(other_storage.rglob('*'))


def test_demo_seed_lifecycle_transitions(tmp_path):
    env_file, url, storage_root, manifest = _write_env(tmp_path)
    _create_schema(url)
    seeded = _run(env_file, manifest)
    assert seeded.returncode == 0, seeded.stderr
    data = _load_manifest(manifest)

    async def scenario():
        from app.storage.base import LocalStorage
        import app.storage.base as storage_base

        storage_base._storage = LocalStorage(storage_root)
        engine, factory = _session(url)
        try:
            async with factory() as session:
                initial = await verify(session, storage_base._storage, data, verify_api=False)
                assert initial.ok(), initial.errors[:10]
                async def user(key: str):
                    return await _fresh(session, User, _id(data, f'account_{key}'))
                async def obj(model, key: str):
                    return await _fresh(session, model, _id(data, key))

                admin = await user('admin')
                admin2 = await user('admin2')
                seller = await user('seller')
                seller2 = await user('seller2')
                seller3 = await user('seller3')
                buyer = await user('buyer')
                buyer3 = await user('buyer3')
                outsider = await user('outsider')
                banned = await user('banned')
                multi_ban = await user('multi_ban')
                multi_buyer = await user('multi_buyer')

                # 0. 封禁账户仍可读通知，但业务写操作被拒绝。
                with pytest.raises(HTTPException) as banned_write:
                    await create_request(RequestCreateIn(product_id=_id(data, 'product_textbook')), banned, session)
                assert banned_write.value.status_code == 403

                # 1. 审核待审商品：认领、拒绝；另一条已认领事项按最新内容通过并批准新标签。
                lamp_case = await obj(__import__('app.models', fromlist=['DisposalCase']).DisposalCase, 'case_review_product_lamp')
                await claim_case(lamp_case.id, admin, session)
                await review_product(lamp_case.id, ReviewDecisionIn(result='rejected', reason='请补充灯罩磕碰近照'), admin, session)
                lamp = await obj(Product, 'product_lamp_pending')
                lamp = await _fresh(session, Product, lamp.id)
                assert lamp.status == 'rejected'

                keyboard = await obj(Product, 'product_keyboard_pending')
                application = (await session.exec(
                    select(ProductTagApplication).where(ProductTagApplication.product_id == keyboard.id)
                )).first()
                assert application is not None and application.status == 'pending'
                keyboard_case = await obj(__import__('app.models', fromlist=['DisposalCase']).DisposalCase, 'case_review_product_keyboard')
                await review_product(
                    keyboard_case.id,
                    ReviewDecisionIn(result='approved', tag_decisions=[TagDecisionIn(application_id=application.id, decision='approve_new')]),
                    admin, session,
                )
                keyboard = await _fresh(session, Product, keyboard.id)
                assert keyboard.status == 'listed'
                application = await _fresh(session, ProductTagApplication, application.id)
                assert application.status == 'approved_new' and application.resolved_category_id is not None
                assert (await session.get(Category, application.resolved_category_id)).name == '静音外设'

                # 2. 拒绝后重提、认领前撤回后重提。
                camera = await obj(Product, 'product_camera_rejected')
                await resubmit(camera.id, __import__('app.schemas.product', fromlist=['ProductUpdateIn']).ProductUpdateIn(
                    title=camera.title, description=camera.description + ' 已补充镜头近照，快门与测光正常。', price_cents=camera.price_cents,
                ), seller2, session)
                camera = await _fresh(session, Product, camera.id)
                assert camera.status == 'pending_review'
                records = (await session.exec(select(ReviewRecord).where(ReviewRecord.product_id == camera.id).order_by(ReviewRecord.id))).all()
                assert [item.result for item in records] == ['rejected', 'pending']

                monitor = await obj(Product, 'product_monitor_resubmitted')
                await withdraw_review(monitor.id, seller2, session)
                monitor = await _fresh(session, Product, monitor.id)
                assert monitor.status == 'delisted'
                await resubmit(monitor.id, __import__('app.schemas.product', fromlist=['ProductUpdateIn']).ProductUpdateIn(
                    description=monitor.description + ' 已补充亮机照片。'
                ), seller2, session)
                monitor = await _fresh(session, Product, monitor.id)
                assert monitor.status == 'pending_review'
                monitor_records = (await session.exec(select(ReviewRecord).where(ReviewRecord.product_id == monitor.id).order_by(ReviewRecord.id))).all()
                assert [item.result for item in monitor_records] == ['rejected', 'withdrawn', 'pending']

                # 3. 搜索别名、价格、受限商品隐藏与收藏。
                result = await search(session, buyer, keyword='山地车', category_ids=None, category_names=None,
                                      price_min_cents=None, price_max_cents=None, page=1, page_size=20)
                assert any(item.id == _id(data, 'product_bike') for item in result.items)
                aliased = await search(session, buyer, keyword=None, category_ids=None, category_names=['课本'],
                                       price_min_cents=None, price_max_cents=None, page=1, page_size=20)
                assert any(item.id == _id(data, 'product_textbook') for item in aliased.items)
                restricted = _id(data, 'product_powerbank')
                assert all(item.id != restricted for item in result.items)
                with pytest.raises(HTTPException) as detail_error:
                    await detail(restricted, buyer, session)
                assert detail_error.value.status_code == 404
                public = await restriction_result(restricted, buyer, session)
                assert public['public_result'].startswith('经核查')
                await add_favorite(_id(data, 'product_textbook'), buyer, session)
                favorites = await my_favorites(buyer, session)
                assert any(item['product_id'] == _id(data, 'product_textbook') and item['valid'] for item in favorites)
                assert any(item['product_id'] == _id(data, 'product_rice_cooker') and not item['valid'] for item in favorites)

                # 待办按当前事项派生；打开通知标读不改变待办。
                todos = await list_todos(seller, session)
                todo_keys = {item['kind'] for item in todos['items']}
                assert {'request_pending', 'completion_confirm'} <= todo_keys

                # 4. 两买方竞争：接受一条，另一条自动关闭；重复接受被拒。
                trade_a = await obj(Trade, 'trade_compete_a')
                trade_b = await obj(Trade, 'trade_compete_b')
                await accept_request(trade_a.id, seller, session)
                trade_a = await _fresh(session, Trade, trade_a.id)
                trade_b = await _fresh(session, Trade, trade_b.id)
                assert trade_a.status == 'in_progress' and trade_b.status == 'closed'
                headphones = await _fresh(session, Product, _id(data, 'product_headphones'))
                assert headphones.status == 'in_transaction'
                with pytest.raises(HTTPException) as accept_error:
                    await accept_request(trade_b.id, seller, session)
                assert accept_error.value.status_code == 409

                # 5. 新建请求、拒绝、撤回。
                textbook = await _fresh(session, Product, _id(data, 'product_textbook'))
                request_a = await create_request(RequestCreateIn(product_id=textbook.id, note='周三中午可以吗？'), outsider, session)
                new_trade = await _fresh(session, Trade, request_a['id'])
                await __import__('app.api.v1.trades', fromlist=['reject_request']).reject_request(
                    new_trade.id, __import__('app.schemas.trade', fromlist=['RejectIn']).RejectIn(reason='已有同学先约'), seller, session
                )
                request_b = await create_request(RequestCreateIn(product_id=textbook.id, note='周五下午可以吗？'), outsider, session)
                await __import__('app.api.v1.trades', fromlist=['withdraw_request']).withdraw_request(
                    request_b['id'], outsider, session
                )
                assert (await _fresh(session, Trade, request_b['id'])).status == 'withdrawn'

                # 6. 多轮约定：拒绝当前提案、再提、同意后清当前确认；双方确认完成。
                progress = await obj(Trade, 'trade_progress')
                round_two = await obj(TradeAgreement, 'agreement_progress_2')
                await reject_agreement(progress.id, round_two.id, buyer, session)
                assert (await _fresh(session, TradeAgreement, round_two.id)).status == 'rejected'
                proposal = await __import__('app.api.v1.trades', fromlist=['propose_agreement']).propose_agreement(
                    progress.id, AgreementProposeIn(delivery_time='周日下午 15:00', delivery_location='3 号宿舍楼下',
                                                    delivery_method='当面自提', amount_cents=33000, payment_method='当面支付',
                                                    payment_timing='交付时'), buyer, session
                )
                await confirm_agreement(progress.id, proposal['id'], seller, session)
                progress = await _fresh(session, Trade, progress.id)
                assert progress.current_agreement_id == proposal['id']
                assert progress.confirm_wait_started_at is None
                await submit_confirmation(progress.id, ConfirmationIn(note='已拿到椅子并付款'), buyer, session)
                await submit_confirmation(progress.id, ConfirmationIn(note='已交付'), seller, session)
                progress = await _fresh(session, Trade, progress.id)
                assert progress.status == 'completed'
                chair = await _fresh(session, Product, _id(data, 'product_chair'))
                assert chair.status == 'delisted'

                # 7. 单方确认到双方完成。
                confirm_trade = await obj(Trade, 'trade_confirm')
                await submit_confirmation(confirm_trade.id, ConfirmationIn(note='已收到并确认'), seller, session)
                confirm_trade = await _fresh(session, Trade, confirm_trade.id)
                assert confirm_trade.status == 'completed'
                assert (await _fresh(session, Product, _id(data, 'product_microwave'))).status == 'delisted'

                # 8. 取消：首约前直接取消、约定后同意、拒绝后申请人撤回。
                kettle = await obj(Trade, 'trade_kettle_no_agreement')
                await propose_cancel(kettle.id, CancelIn(reason='临时不需要'), buyer, session)
                assert (await _fresh(session, Trade, kettle.id)).status == 'terminated'

                cancel_pending = await obj(Trade, 'trade_cancel_pending')
                await confirm_cancel(cancel_pending.id, CancelIn(reason='同意取消'), buyer3, session)
                assert (await _fresh(session, Trade, cancel_pending.id)).status == 'terminated'

                cancel_refused = await obj(Trade, 'trade_cancel_refused')
                await withdraw_cancel(cancel_refused.id, seller3, session)
                cancel_refused = await _fresh(session, Trade, cancel_refused.id)
                assert cancel_refused.status == 'in_progress' and cancel_refused.cancel_requested_by_id is None

                # 9. 争议：卖方确认解决后恢复，当前确认清空、等待不自动开始。
                disputed = await obj(Trade, 'trade_disputed_open')
                await resolve_dispute(disputed.id, CancelIn(reason='同意补送并完成'), seller, session)
                disputed = await _fresh(session, Trade, disputed.id)
                assert disputed.status == 'in_progress'
                assert disputed.confirm_wait_started_at is None
                current = (await session.exec(select(CompletionConfirmation).where(
                    CompletionConfirmation.trade_id == disputed.id, CompletionConfirmation.is_current.is_(True)))).all()
                assert current == []
                old = (await session.exec(select(CompletionConfirmation).where(
                    CompletionConfirmation.trade_id == disputed.id, CompletionConfirmation.is_current.is_(False)))).all()
                assert old

                # 10. 冻结解冻：剩余计时续算。
                frozen = await obj(Trade, 'trade_frozen')
                await unfreeze(frozen.id, UnfreezeIn(reason='已核查并协商继续', case_id=_id(data, 'case_trade_frozen')), admin, session)
                frozen = await _fresh(session, Trade, frozen.id)
                assert not frozen.frozen and frozen.confirm_wait_paused_at is None
                assert frozen.confirm_wait_started_at is not None

                # 11. 超时扫描：真实扫描触发异常、冻结与新事项。
                timeout = await obj(Trade, 'trade_timeout')
                old_settings = trade_timeout.get_settings
                trade_timeout.get_settings = lambda: SimpleNamespace(trade_confirm_timeout_days=7)
                try:
                    assert await trade_timeout.scan_once(session, trade_ids=(timeout.id,)) == 1
                finally:
                    trade_timeout.get_settings = old_settings
                timeout = await _fresh(session, Trade, timeout.id)
                assert timeout.status == 'abnormal' and timeout.frozen
                abnormal_case = (await session.exec(
                    select(__import__('app.models', fromlist=['DisposalCase']).DisposalCase).where(
                        __import__('app.models', fromlist=['DisposalCase']).DisposalCase.trade_id == timeout.id,
                        __import__('app.models', fromlist=['DisposalCase']).DisposalCase.case_type == 'abnormal_trade')
                )).first()
                assert abnormal_case is not None

                # 12. 管理员调整异常交易并解冻；不伪造双方确认。
                abnormal = await obj(Trade, 'trade_abnormal_admin')
                await adjust_status(abnormal.id, AdjustIn(to_status='in_progress', reason='核实未交付，退回后继续', case_id=_id(data, 'case_trade_abnormal')), admin, session)
                abnormal = await _fresh(session, Trade, abnormal.id)
                assert abnormal.status == 'in_progress'
                confirmations = (await session.exec(select(CompletionConfirmation).where(
                    CompletionConfirmation.trade_id == abnormal.id, CompletionConfirmation.is_current.is_(True)))).all()
                assert confirmations == []
                await unfreeze(abnormal.id, UnfreezeIn(reason='状态恢复后解除冻结', case_id=_id(data, 'case_trade_abnormal')), admin, session)
                assert not (await _fresh(session, Trade, abnormal.id)).frozen

                # 13. 封禁解除：解冻关联交易，保留历史封禁记录。
                await unban_user(banned.id, UnbanIn(lift_reason='整改完成，解除封禁'), admin, session)
                banned = await _fresh(session, User, banned.id)
                assert banned.status == 'normal'
                banned_trade = await _fresh(session, Trade, _id(data, 'trade_ban_side'))
                assert not banned_trade.frozen
                old_restriction = await _fresh(session, __import__('app.models', fromlist=['AccountRestriction']).AccountRestriction,
                                               _id(data, 'restriction_ban_old'))
                assert old_restriction.status == 'lifted'

                # 14. 多重限制：解除封禁不误清另一事项的交易冻结。
                await unban_user(multi_ban.id, UnbanIn(lift_reason='申诉通过，解除封禁'), admin, session)
                multi_ban = await _fresh(session, User, multi_ban.id)
                assert multi_ban.status == 'normal'
                guitar = await _fresh(session, Product, _id(data, 'product_guitar'))
                assert not guitar.display_restricted
                multi_trade = await _fresh(session, Trade, _id(data, 'trade_multi_restriction'))
                assert multi_trade.frozen and multi_trade.frozen_case_id == _id(data, 'case_trade_multi_freeze')

                # 15. 处理中举报形成不予处理结论；举报人收到结论原因，被举报人无新增处置通知。
                seller_notifications_before = (await session.exec(select(Notification).where(Notification.user_id == seller.id))).all()
                await decide_report(_id(data, 'case_report_product_processing'),
                                    ReportDecisionIn(outcome='unfounded', reason='描述与私聊时间不一致但不足以认定误导'), admin, session)
                processing_report = await obj(Report, 'report_product_processing')
                assert processing_report.status == 'unfounded' and processing_report.public_result is None
                seller_notifications_after = (await session.exec(select(Notification).where(Notification.user_id == seller.id))).all()
                assert len(seller_notifications_after) == len(seller_notifications_before)

                # 16. 已结举报拒绝重报与补充；我的举报显示结论原因。
                with pytest.raises(HTTPException) as re_report:
                    await create_report(ReportCreateIn(target_type='product', target_id=_id(data, 'product_blender'),
                                                       reason='同一问题再次举报'), buyer3, session)
                assert re_report.value.status_code == 409
                with pytest.raises(HTTPException) as supplement:
                    await add_supplement(_id(data, 'report_unfounded'), SupplementIn(content='再补充一点'), buyer3, session)
                assert supplement.value.status_code == 409
                mine = await my_reports(buyer3, session)
                closed = next(item for item in mine if item['id'] == _id(data, 'report_unfounded'))
                assert closed['public_result'] is None and closed['result_reason']

                # 17. 受影响者申辩与管理员回复；展示限制可按依据撤销。
                await submit_appeal(_id(data, 'case_report_product_handled'), __import__('app.api.v1.my_cases', fromlist=['StatementIn']).StatementIn(content='已妥善回收鼓包电池，申请恢复展示'), seller2, session)
                await admin_reply(_id(data, 'case_report_product_handled'), CaseMessageIn(content='申辩收到，先维持限制；如已回收可补充回收凭证。'), admin, session)
                case_messages = (await session.exec(select(__import__('app.models', fromlist=['DisposalMessage']).DisposalMessage).where(
                    __import__('app.models', fromlist=['DisposalMessage']).DisposalMessage.case_id == _id(data, 'case_report_product_handled')
                ).order_by(__import__('app.models', fromlist=['DisposalMessage']).DisposalMessage.id))).all()
                assert any(message.kind == 'appeal' for message in case_messages)
                await restore_product_display(_id(data, 'product_powerbank'),
                                              RestoreDisplayIn(case_id=_id(data, 'case_report_product_handled'), reason='已提交回收凭证，撤销展示限制'),
                                              admin, session)
                powerbank = await _fresh(session, Product, _id(data, 'product_powerbank'))
                assert not powerbank.display_restricted
                with pytest.raises(HTTPException) as gone:
                    await restriction_result(powerbank.id, buyer, session)
                assert gone.value.status_code == 404

                # 18. 通知已读与聊天已读独立；打开通知不改变会话未读。
                notification = await obj(Notification, 'notif_seller_compete_a')
                todos_before_read = {item['kind'] for item in (await list_todos(seller, session))['items']}
                await mark_read(notification.id, seller, session)
                assert (await _fresh(session, Notification, notification.id)).is_read
                assert {item['kind'] for item in (await list_todos(seller, session))['items']} == todos_before_read
                frozen_branch = await obj(Conversation, 'conversation_trade_multi_restriction')
                with pytest.raises(HTTPException) as frozen_im:
                    await send_message(frozen_branch.id, MessageIn(content='能约个时间吗？'), multi_buyer, session)
                assert frozen_im.value.status_code == 403
                normal = await obj(Conversation, 'conversation_normal')
                trade_branch = await obj(Conversation, 'conversation_trade_compete_a')
                normal_last = (await session.exec(select(Message).where(Message.conversation_id == normal.id).order_by(Message.id.desc()).limit(1))).first()
                trade_last = (await session.exec(select(Message).where(Message.conversation_id == trade_branch.id).order_by(Message.id.desc()).limit(1))).first()
                await advance_read(normal.id, ReadAdvanceIn(last_displayed_message_id=normal_last.id), seller, session)
                trade_read = (await session.exec(select(ConversationRead).where(
                    ConversationRead.conversation_id == trade_branch.id, ConversationRead.user_id == seller.id))).first()
                assert trade_read is None or trade_read.last_read_message_id < trade_last.id

                # 19. 分类维护：改名保留旧别名、停用已用分类、删除未关联分类。
                digital = await obj(Category, 'category_digital')
                renamed = await update_category(digital.id, __import__('app.schemas.category', fromlist=['CategoryUpdateIn']).CategoryUpdateIn(name='数码与电子'), admin, session)
                assert renamed.name == '数码与电子'
                alias = (await session.exec(select(CategoryAlias).where(CategoryAlias.category_id == digital.id,
                                                                       CategoryAlias.name == '数码电子', CategoryAlias.removed_at.is_(None)))).first()
                assert alias is not None
                unused = await obj(Category, 'category_unused')
                await delete_category(unused.id, admin, session)
                assert (await _fresh(session, Category, unused.id)).deleted_at is not None
                with pytest.raises(HTTPException) as used_delete:
                    await delete_category(digital.id, admin, session)
                assert used_delete.value.status_code == 400
                sports = await obj(Category, 'category_sports')
                disabled = await update_category(
                    sports.id,
                    __import__('app.schemas.category', fromlist=['CategoryUpdateIn']).CategoryUpdateIn(status='disabled'),
                    admin, session,
                )
                assert disabled.status == 'disabled'
                racket_tags = (await session.exec(select(__import__('app.models', fromlist=['ProductTag']).ProductTag).where(
                    __import__('app.models', fromlist=['ProductTag']).ProductTag.product_id == _id(data, 'product_racket')
                ))).all()
                assert any(tag.category_id == sports.id for tag in racket_tags)

                # 20. 权限：非交易方详情、非认领管理员事项。
                with pytest.raises(HTTPException) as private_trade:
                    await trade_detail(_id(data, 'trade_frozen'), outsider, session)
                assert private_trade.value.status_code == 404
                with pytest.raises(HTTPException) as claimed_case:
                    await case_detail(_id(data, 'case_review_product_keyboard'), admin2, session)
                assert claimed_case.value.status_code == 403

                # 21. 统计显式范围：只统计范围内完成的交易。
                from app.api.v1.admin.stats import stats
                now = datetime.now(UTC)
                start = (now - timedelta(days=7)).date().isoformat()
                end = now.date().isoformat()
                stats_data = await stats(admin, session, date_from=start, date_to=end)
                expected = (await session.exec(select(Trade).where(
                    Trade.status == 'completed',
                    Trade.finished_at >= datetime.combine(datetime.fromisoformat(start).date(), datetime.min.time(), tzinfo=UTC),
                    Trade.finished_at <= now,
                ))).all()
                assert stats_data['range']['completed_trades'] == len(expected)
                unfiltered = await stats(admin, session, date_from=None, date_to=None)
                assert unfiltered['range']['completed_trades'] is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_demo_seed_recovers_commit_with_lost_manifest_write(tmp_path):
    env_file, url, storage_root, manifest = _write_env(tmp_path)
    _create_schema(url, existing=False)
    code = """
import sys
import app.devtools.demo_seed as seed
original = seed.write_private_json
def failing(path, payload):
    if payload.get('complete'):
        raise RuntimeError('injected manifest write failure after commit')
    return original(path, payload)
seed.write_private_json = failing
raise SystemExit(seed.main(sys.argv[1:]))
"""
    failed = subprocess.run(
        [sys.executable, '-X', 'utf8', '-c', code, '--env-file', str(env_file), '--manifest', str(manifest)],
        cwd=Path(__file__).resolve().parents[1], env=_clean_env(), capture_output=True, text=True, encoding='utf-8', check=False,
    )
    assert failed.returncode != 0 and 'RuntimeError' in failed.stderr
    partial = _load_manifest(manifest)
    assert not partial['complete'] and partial['objects'] and partial['files']

    retried = _run(env_file, manifest)
    assert retried.returncode == 0, retried.stderr
    data = _load_manifest(manifest)
    assert data['complete']
    assert len(data['accounts']) == len(catalog.ACCOUNTS)
    assert len(data['objects']) == len(partial['objects'])

    async def counts():
        from sqlalchemy import text
        engine, factory = _session(url)
        try:
            async with factory() as session:
                result = {}
                for table in Base.metadata.sorted_tables:
                    result[table.name] = (await session.exec(text(f'SELECT count(*) FROM "{table.name}"'))).one()[0]
                return result
        finally:
            await engine.dispose()
    after = asyncio.run(counts())
    assert after['users'] == len(catalog.ACCOUNTS)
    assert after['products'] == len(catalog.PRODUCTS)
    assert after['trades'] == len(catalog.TRADES)
    assert after['reports'] == len(catalog.REPORTS)


def test_demo_seed_recovers_lost_upload_response(tmp_path):
    env_file, url, storage_root, manifest = _write_env(tmp_path)
    _create_schema(url, existing=False)
    failed = _run(env_file, manifest, fault=True, response_lost=True)
    assert failed.returncode != 0 and 'RuntimeError' in failed.stderr
    partial = _load_manifest(manifest)
    assert not partial['complete'] and len(partial['files']) == 2
    assert len({p.relative_to(storage_root).as_posix() for p in storage_root.rglob('*') if p.is_file()}) == 2
    retried = _run(env_file, manifest)
    assert retried.returncode == 0, retried.stderr
    data = _load_manifest(manifest)
    assert data['complete']
    assert {p.relative_to(storage_root).as_posix() for p in storage_root.rglob('*') if p.is_file()} == set(data['files'][name]['key'] for name in data['files'])
