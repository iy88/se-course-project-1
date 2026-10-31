"""Persistent demonstration data. Run migrations separately before using this command.

The manifest is private and binds a seed to its database and storage target. Existing
business data is never cleared or adopted. Re-running preserves subsequent edits.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import load_settings, resolve_env_file
from app.devtools._support import credentials_lock, write_private_json

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / 'backend/tests/acceptance_real/assets'
DEFAULT_MANIFEST = ROOT / 'var/demo/manifest.json'


def _target(settings) -> str:
    # Never put connection credentials in the manifest or terminal.
    from sqlalchemy.engine import make_url
    database = make_url(settings.database_url).set(password=None).render_as_string(hide_password=True)
    parts = [database, settings.database_schema, settings.storage_backend,
             str(settings.storage_local_root or ''), settings.oss_endpoint,
             settings.oss_media_bucket, settings.oss_evidence_bucket, settings.storage_key_prefix]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def _load(path: Path, target: str) -> dict:
    if path.exists():
        if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ValueError('manifest 必须是权限为 0600 的普通文件')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1 or data.get('target') != target:
            raise ValueError('manifest 版本或资源目标不匹配')
        return data
    tag = secrets.token_hex(8)
    names = {'admin': ('演示管理员', 'admin'), 'admin2': ('演示管理员二', 'admin'),
             'seller': ('演示卖家', 'user'), 'buyer': ('演示买家', 'user'),
             'buyer2': ('演示买家二', 'user'), 'outsider': ('演示用户', 'user'),
             'frozen_seller': ('冻结卖家', 'user'), 'frozen_buyer': ('冻结买家', 'user'),
             'banned': ('封禁用户', 'user'), 'ban_seller': ('受限交易卖家', 'user'),
             'timeout_seller': ('超时卖家', 'user'), 'timeout_buyer': ('超时买家', 'user')}
    return {'version': 1, 'target': target, 'tag': tag, 'complete': False,
            'accounts': {k: {'email': f'demo-{k}-{tag}@example.com', 'password': secrets.token_urlsafe(24),
                             'display_name': name, 'role': role} for k, (name, role) in names.items()},
            'objects': {}, 'files': {}}


async def _seed(settings, manifest: Path, data: dict) -> None:
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import select
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.security import hash_password, verify_password
    from app.models.category import Category, CategoryAlias
    from app.models.governance import (
        DisposalCase,
        DisposalMessage,
        Notification,
        Report,
        ReportSupplement,
    )
    from app.models.im import Conversation, Message
    from app.models.product import (
        Comment,
        Favorite,
        Product,
        ProductImage,
        ProductTag,
        ProductTagApplication,
        ProhibitedItem,
        ReviewRecord,
    )
    from app.models.stored_object import StoredObject
    from app.models.trade import (
        CompletionConfirmation,
        Trade,
        TradeAgreement,
        TradeReview,
        TradeTransition,
    )
    from app.models.user import User
    from app.storage.base import StorageAlreadyExists, build_storage, make_key

    options = {}
    if settings.database_url.startswith('postgresql+asyncpg:'):
        options['connect_args'] = {'server_settings': {'search_path': f'"{settings.database_schema}"'}}
    engine = create_async_engine(settings.database_url, **options)
    if settings.database_url.startswith('sqlite'):
        @event.listens_for(engine.sync_engine, 'connect')
        def _foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
    storage = build_storage(settings)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def ensure_file(name: str, namespace: str, filename: str, asset: str, content: bytes) -> dict:
        entry = data['files'].get(name)
        if entry is None:
            entry = {'key': make_key(namespace, filename), 'asset': asset}
            data['files'][name] = entry
            # Persist the key before the first remote write, including its uncertainty window.
            write_private_json(manifest, data)
        if not storage.exists(entry['key']):
            try:
                storage.save_to_key(entry['key'], content)
            except StorageAlreadyExists:
                # Another writer or a successful write with a lost response: compare below.
                pass
        if storage.open(entry['key']) != content:
            raise ValueError('已登记演示文件内容不一致；拒绝覆盖')
        return entry
    try:
        async with factory() as session:
            if data['complete']:
                for account in data['accounts'].values():
                    user = await session.get(User, account['id'])
                    if user is None or user.email != account['email']:
                        raise ValueError('清单中的演示账号不存在或已更换邮箱；不自动接管')
                for entry in data['files'].values():
                    if not storage.exists(entry['key']):
                        raise ValueError('清单中的文件缺失；请人工检查存储')
                return
            # Recover a commit whose acknowledgement or final manifest write failed.
            found_accounts = [(await session.exec(select(User).where(User.email == account['email']))).first()
                              for account in data['accounts'].values()]
            if any(found_accounts):
                if (not data['objects'] or not all(found_accounts) or
                    any(user.id != account.get('id') or user.role != account['role'] or
                        not verify_password(account['password'], user.password_hash)
                        for user, account in zip(found_accounts, data['accounts'].values()))):
                    raise ValueError('检测到部分或冲突账号；拒绝接管，请人工核对')
                for key, object_id in data['objects'].items():
                    model = (Product if key.startswith('product_') else Trade if key.startswith('trade_')
                             else Conversation if key.startswith('conversation_') else DisposalCase if key.startswith('case_')
                             else Category if key.startswith('category') else TradeAgreement if key.startswith('agreement_')
                             else ReportSupplement if key == 'report_supplement' else Report if key.startswith('report')
                             else Comment if key == 'comment' else None)
                    if model is None or await session.get(model, object_id) is None:
                        raise ValueError('待恢复清单的业务记录不完整；请人工核对')
                for entry in data['files'].values():
                    registered = await session.get(StoredObject, entry['key'])
                    if registered is None or registered.state != 'committed' or not storage.exists(entry['key']):
                        raise ValueError('待恢复清单的对象登记不完整；请人工核对')
                data['complete'] = True
                write_private_json(manifest, data)
                return
            # IDs recorded before a failed commit are advisory only; no existing row is adopted.
            for key, account in data['accounts'].items():
                found = (await session.exec(select(User).where(User.email == account['email']))).first()
                if found is not None:
                    raise ValueError(f'演示邮箱已存在（{key}）；拒绝接管')
                user = User(email=account['email'], password_hash=hash_password(account['password']),
                            display_name=account['display_name'], role=account['role'])
                session.add(user)
                await session.flush()
                account['id'] = user.id
            uid = {k: v['id'] for k, v in data['accounts'].items()}
            objects = {}
            async def add(key, obj):
                session.add(obj)
                await session.flush()
                objects[key] = obj.id
                return obj
            category = await add('category', Category(name=f'演示闲置-{data["tag"]}', created_by_id=uid['admin']))
            session.add(CategoryAlias(category_id=category.id, name=f'演示别名-{data["tag"]}', created_by_id=uid['admin']))
            await add('category_unused', Category(name=f'演示待整理-{data["tag"]}', created_by_id=uid['admin']))
            session.add(ProhibitedItem(group_name='演示禁发范围', content='危险品及管制物品不得发布', updated_by_id=uid['admin']))
            specs = [
                ('listed', '校园自行车', 'listed', 'product_bike.jpg'),
                ('pending', '台灯待审核', 'pending_review', 'product_lamp.jpg'),
                ('rejected', '相机待修改', 'rejected', 'product_camera.jpg'),
                ('request', '教材购买请求', 'listed', 'product_textbook.jpg'),
                ('progress', '键盘交易中', 'in_transaction', 'product_keyboard.jpg'),
                ('completed', '球拍已完成', 'delisted', 'product_racket.jpg'),
                ('reviewed', '相机已评价', 'delisted', 'product_camera.jpg'),
                ('disputed', '杯子交易争议', 'in_transaction', 'product_mug.jpg'),
                ('confirm', '笔记本单方确认', 'in_transaction', 'product_notes.jpg'),
                ('delisted', '已下架台灯', 'delisted', 'product_lamp.jpg'),
                ('frozen', '冻结交易', 'in_transaction', 'product_second.jpg'),
                ('ban_progress', '受限账号已有交易', 'in_transaction', 'product_second2.jpg'),
                ('ban_request', '受限账号购买请求', 'listed', 'product_bike.jpg'),
                ('timeout', '待扫描超时交易', 'in_transaction', 'product_camera.jpg'),
            ]
            products = {}
            now = datetime.now(UTC)
            for key, title, status, asset in specs:
                seller = uid['frozen_seller'] if key == 'frozen' else (uid['ban_seller'] if key.startswith('ban_') else (uid['timeout_seller'] if key == 'timeout' else uid['seller']))
                product = await add('product_' + key, Product(seller_id=seller, title='演示｜' + title,
                    description='演示数据：校园闲置物品，详情可与卖家沟通。', price_cents=8800, status=status,
                    listed_at=now if status in ('listed', 'in_transaction', 'delisted') else None,
                    reject_reason='请补充清晰图片' if status == 'rejected' else None))
                products[key] = product
                session.add(ProductTag(product_id=product.id, category_id=category.id))
                content = (ASSETS / asset).read_bytes()
                file_entry = ensure_file(key, 'product', asset, asset, content)
                session.add(ProductImage(product_id=product.id, file_key=file_entry['key'], sort=0))
                session.add(StoredObject(key=file_entry['key'], namespace='product', bucket_role='media',
                    owner_id=seller, content_type='image/jpeg', size_bytes=len(content),
                    state='committed', ref_type='product', ref_id=product.id, committed_at=now))
                result = 'pending' if status == 'pending_review' else ('rejected' if status == 'rejected' else 'approved')
                review = ReviewRecord(product_id=product.id, content_json={'title': product.title, 'description': product.description,
                    'price_cents': product.price_cents}, result=result, reviewer_id=None if result == 'pending' else uid['admin'],
                    reviewed_at=None if result == 'pending' else now, reason=product.reject_reason)
                if result == 'pending':
                    case = await add('case_product_review', DisposalCase(case_type='product_review', product_id=product.id,
                        subject_user_id=uid['seller'], title='演示商品审核'))
                    review.case_id = case.id
                    session.add(ProductTagApplication(product_id=product.id, requested_name=f'演示新标签-{data["tag"]}'))
                session.add(review)
            session.add(Favorite(user_id=uid['buyer'], product_id=products['listed'].id))
            comment = await add('comment', Comment(product_id=products['listed'].id, author_id=uid['buyer'], content='请问可以在校内面交吗？'))
            session.add(Comment(product_id=products['listed'].id, author_id=uid['seller'], content='可以，具体时间私聊。',
                reply_to_comment_id=comment.id, reply_to_user_id=uid['buyer']))
            for key, buyer, status in [('request_buyer', 'buyer', 'pending_acceptance'), ('request_buyer2', 'buyer2', 'pending_acceptance'),
                                       ('progress', 'buyer', 'in_progress'), ('completed', 'buyer', 'completed'), ('reviewed', 'buyer2', 'completed'), ('disputed', 'buyer2', 'disputed'),
                                       ('confirm', 'buyer', 'in_progress'), ('frozen', 'frozen_buyer', 'disputed'),
                                       ('ban_progress', 'banned', 'in_progress'), ('ban_request', 'banned', 'pending_acceptance'),
                                       ('timeout', 'timeout_buyer', 'in_progress')]:
                product_key = 'request' if key.startswith('request_') else key
                product = products[product_key]
                seller = uid['frozen_seller'] if key == 'frozen' else (uid['ban_seller'] if key.startswith('ban_') else (uid['timeout_seller'] if key == 'timeout' else uid['seller']))
                accepted_time = now - timedelta(days=settings.trade_confirm_timeout_days + 2) if key == 'timeout' else now
                trade = await add('trade_' + key, Trade(product_id=product.id, buyer_id=uid[buyer], seller_id=seller,
                    status=status, request_note='希望校内交付', created_at=accepted_time, accepted_at=accepted_time if status != 'pending_acceptance' else None,
                    finished_at=now if status == 'completed' else None,
                    product_snapshot_json={'product_id': product.id, 'title': product.title, 'description': product.description, 'price_cents': product.price_cents, 'images': [data['files'][product_key]['key']], 'tags': [category.name], 'captured_at': accepted_time.isoformat()} if status != 'pending_acceptance' else None))
                session.add(TradeTransition(trade_id=trade.id, to_status='pending_acceptance', actor_id=uid[buyer], actor_role='buyer', trigger='request_created', created_at=accepted_time))
                if status != 'pending_acceptance':
                    session.add(TradeTransition(trade_id=trade.id, from_status='pending_acceptance', to_status='in_progress', actor_id=seller, actor_role='seller', trigger='accepted', created_at=accepted_time))
                    if status != 'in_progress':
                        session.add(TradeTransition(trade_id=trade.id, from_status='in_progress', to_status=status, actor_id=uid[buyer], actor_role='buyer', trigger='demo_' + status))
                conv = await add('conversation_' + key, Conversation(type='trade', trade_id=trade.id,
                    user_low_id=min(uid[buyer], seller), user_high_id=max(uid[buyer], seller), archived=status == 'completed', archived_at=now if status == 'completed' else None))
                session.add(Message(conversation_id=conv.id, sender_id=uid[buyer], content='你好，我们可以商量交付时间吗？'))
                if key in ('confirm', 'timeout'):
                    agreement = await add('agreement_' + key, TradeAgreement(trade_id=trade.id, proposer_id=seller,
                        delivery_time='本周末', delivery_location='学校图书馆', delivery_method='当面交付',
                        amount_cents=8800, payment_method='当面支付', payment_timing='交付时', status='confirmed', proposed_at=accepted_time, decided_at=accepted_time))
                    trade.current_agreement_id = agreement.id
                    started = now - timedelta(days=settings.trade_confirm_timeout_days + 1) if key == 'timeout' else now
                    trade.confirm_wait_started_at = started
                    session.add(CompletionConfirmation(trade_id=trade.id, confirmer_id=uid[buyer], confirmed_at=started))
                if status == 'completed':
                    agreement = await add('agreement_' + key, TradeAgreement(trade_id=trade.id, proposer_id=uid['seller'],
                        delivery_time='校内约定时间', delivery_location='学校图书馆', delivery_method='当面交付',
                        amount_cents=8800, payment_method='当面支付', payment_timing='交付时', status='confirmed', decided_at=now))
                    trade.current_agreement_id = agreement.id
                    session.add(CompletionConfirmation(trade_id=trade.id, confirmer_id=uid[buyer]))
                    session.add(CompletionConfirmation(trade_id=trade.id, confirmer_id=seller))
                    if key == 'reviewed':
                        session.add(TradeReview(trade_id=trade.id, reviewer_id=uid[buyer], reviewee_id=seller,
                            rating=5, content='演示评价：沟通顺利。'))
                if status == 'disputed':
                    agreement = await add('agreement_' + key, TradeAgreement(trade_id=trade.id, proposer_id=seller,
                        delivery_time='校内约定时间', delivery_location='学校图书馆', delivery_method='当面交付',
                        amount_cents=8800, payment_method='当面支付', payment_timing='交付时', status='confirmed', decided_at=now))
                    trade.current_agreement_id = agreement.id
                    session.add(CompletionConfirmation(trade_id=trade.id, confirmer_id=uid[buyer], is_current=False))
                    case = await add('case_dispute_' + key, DisposalCase(case_type='trade_dispute', trade_id=trade.id, title='演示交易争议'))
                    if key == 'frozen':
                        trade.frozen = True
                        trade.frozen_reason = '演示管理冻结'
                        trade.frozen_at = now
                        trade.frozen_by_id = uid['admin']
                        trade.frozen_case_id = case.id
            banned_user = await session.get(User, uid['banned'])
            ban_case = await add('case_ban', DisposalCase(case_type='account_ban', status='disposed',
                claimed_by_id=uid['admin'], claimed_at=now, subject_user_id=uid['banned'], title='演示账号封禁',
                conclusion='封禁账号', conclusion_reason='演示违规处置', basis='演示管理事项', disposed_at=now))
            from app.services.moderation import ban_user
            await session.flush()
            await ban_user(session, banned_user, reason='演示违规处置', basis='演示管理事项',
                case_id=ban_case.id, admin_id=uid['admin'])
            from io import BytesIO

            from PIL import Image, ImageOps
            image_buffer = BytesIO()
            with Image.open(ASSETS / 'product_racket.jpg') as source_image:
                ImageOps.fit(source_image.convert('RGB'), (256, 256)).save(image_buffer, format='JPEG', quality=90)
            avatar_content = image_buffer.getvalue()
            avatar = ensure_file('avatar', 'avatar', 'avatar.jpg', 'product_racket.jpg', avatar_content)
            avatar_user = await session.get(User, uid['outsider'])
            avatar_user.avatar_pending_key = avatar['key']
            avatar_user.avatar_review_status = 'pending'
            session.add(StoredObject(key=avatar['key'], namespace='avatar', bucket_role='media', owner_id=uid['outsider'],
                content_type='image/jpeg', size_bytes=len(avatar_content), state='committed', ref_type='avatar',
                ref_id=uid['outsider'], committed_at=now))
            await add('case_avatar', DisposalCase(case_type='avatar_review', subject_user_id=uid['outsider'],
                avatar_key=avatar['key'], title='演示头像审核'))
            normal = await add('conversation_normal', Conversation(type='normal', user_low_id=min(uid['buyer'], uid['seller']),
                user_high_id=max(uid['buyer'], uid['seller'])))
            session.add(Message(conversation_id=normal.id, sender_id=uid['buyer'], content='你好，请问商品还在吗？'))
            report_content = (ASSETS / 'evidence_listing.jpg').read_bytes()
            entry = ensure_file('evidence', 'report', 'evidence_listing.jpg', 'evidence_listing.jpg', report_content)
            report = await add('report', Report(reporter_id=uid['buyer2'], target_type='product', target_id=products['listed'].id,
                reason='演示举报：请核实商品信息', evidence_keys=[entry['key']]))
            session.add(StoredObject(key=entry['key'], namespace='report', bucket_role='evidence', owner_id=uid['buyer2'],
                content_type='image/jpeg', size_bytes=len(report_content), state='committed', ref_type='report', ref_id=report.id, committed_at=now))
            await add('case_report', DisposalCase(case_type='report', report_id=report.id, title='演示举报待处理'))
            supplement_content = (ASSETS / 'evidence_chat.jpg').read_bytes()
            supplement_file = ensure_file('supplement', 'report', 'evidence_chat.jpg', 'evidence_chat.jpg', supplement_content)
            supplement = await add('report_supplement', ReportSupplement(report_id=report.id, author_id=uid['buyer2'],
                content='演示补充说明：请一并核查聊天记录。', evidence_keys=[supplement_file['key']]))
            session.add(StoredObject(key=supplement_file['key'], namespace='report', bucket_role='evidence',
                owner_id=uid['buyer2'], content_type='image/jpeg', size_bytes=len(supplement_content), state='committed',
                ref_type='report_supplement', ref_id=supplement.id, committed_at=now))
            handled_report = await add('report_handled', Report(reporter_id=uid['buyer'], target_type='product',
                target_id=products['rejected'].id, reason='演示举报已处理', status='unfounded', result_confirmed=True,
                public_result='依据不足，不予处理', result_reason='演示核查结果', closed_at=now))
            handled_case = await add('case_report_handled', DisposalCase(case_type='report', status='disposed', report_id=handled_report.id,
                claimed_by_id=uid['admin'], claimed_at=now, title='演示已处理举报', conclusion='不予处理',
                conclusion_reason='演示核查结果', basis='演示核查', disposed_at=now))
            session.add(DisposalMessage(case_id=handled_case.id, sender_id=uid['admin'], role='admin', kind='inquiry', content='请说明商品信息。'))
            session.add(DisposalMessage(case_id=handled_case.id, sender_id=uid['seller'], role='user', kind='statement', content='商品信息已按实际情况填写。'))
            session.add(DisposalMessage(case_id=handled_case.id, sender_id=uid['admin'], role='admin', kind='reply', content='经核查，现有证据不足。'))
            from app.services.audit import record_event
            await record_event(session, 'demo.seed', target_type='demo', target_id=data['tag'], actor_id=uid['admin'], actor_role='admin',
                after={'description': '演示数据初始化'})
            session.add(Notification(user_id=uid['seller'], type='request_created', title='收到购买请求', content='演示用户发起购买请求',
                link_type='trade', link_id=objects['trade_request_buyer']))
            data['objects'] = objects
            # The manifest is prepared before commit. A commit whose outcome is unknown is
            # deliberately refused on retry if its account emails already exist.
            write_private_json(manifest, data)
            await session.commit()
            data['complete'] = True
            write_private_json(manifest, data)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', help='dotenv path; defaults to APP_ENV_FILE or backend/.env.dev')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST, help='private manifest path')
    args = parser.parse_args(argv)
    try:
        path = args.manifest.expanduser().absolute()
        env_file = resolve_env_file(args.env_file)
        # Imports that use get_settings must see the selected file too.
        os.environ['APP_ENV_FILE'] = str(env_file)
        from app.core.config import get_settings
        get_settings.cache_clear()
        settings = load_settings(env_file)
        settings.prepare_runtime_paths()
        with credentials_lock(path):
            data = _load(path, _target(settings))
            write_private_json(path, data)
            asyncio.run(_seed(settings, path, data))
        print(f'demo seed ready; private manifest: {path}')
        return 0
    except ValueError as exc:
        print(f'demo seed failed: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary avoids disclosing resource credentials
        print(f'demo seed failed: {type(exc).__name__}; 请检查迁移、配置及资源访问', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
