from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.admin.cases import claim_case
from app.api.v1.avatars import AvatarIn, DecisionIn, decide_avatar, submit_avatar
from app.db.session import Base
from app.models import DisposalCase, User
from app.models.stored_object import StoredObject
from app.models.upload_lease import UploadLease
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.mark.asyncio
@pytest.mark.parametrize("self_review", [False, True])
async def test_avatar_moderation(tmp_path, self_review):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "avatars.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            user = User(email='user@example.com', display_name='User', password_hash='x')
            admin = User(email='admin@example.com', display_name='Admin', password_hash='x', role='admin')
            db.add_all([user, admin])
            await db.commit()
            outsider = user if not self_review else admin
            if self_review:
                user.role = 'admin'
                admin = user
                await db.commit()
            key = 'avatar/00000000000000000000000000000001.png'
            db.add(UploadLease(id='a' * 32, key=key, owner_id=user.id, namespace='avatar', filename='a.png', content_type='image/png', size_bytes=10, sha256='a' * 64, expires_at=datetime.now(UTC) + timedelta(hours=1), state='completed'))
            db.add(StoredObject(key=key, namespace='avatar', bucket_role='media', owner_id=user.id, content_type='image/png', size_bytes=10))
            await db.commit()
            result = await submit_avatar(AvatarIn(key=key), user, db)
            case = await db.get(DisposalCase, result['case_id'])
            assert case is not None
            await claim_case(case.id, admin, db)
            await db.refresh(case)
            duplicate = await submit_avatar(AvatarIn(key=key), user, db)
            assert duplicate['case_id'] == case.id
            assert user.avatar_key is None and user.avatar_review_status == 'pending'
            with pytest.raises(HTTPException) as exc:
                await decide_avatar(case.id, DecisionIn(key=key, approved=True), outsider, db)
            assert exc.value.status_code == 403
            await decide_avatar(case.id, DecisionIn(key=key, approved=False, reason='图片不合适'), admin, db)
            assert user.avatar_key is None and user.avatar_review_reason == '图片不合适'
            result = await submit_avatar(AvatarIn(key=key), user, db)
            case = await db.get(DisposalCase, result['case_id'])
            assert case is not None
            await claim_case(case.id, admin, db)
            await db.refresh(case)
            await decide_avatar(case.id, DecisionIn(key=key, approved=True), admin, db)
            assert user.avatar_key == key and user.avatar_review_status == 'approved'
            with pytest.raises(HTTPException) as exc:
                await decide_avatar(case.id, DecisionIn(key=key, approved=True), admin, db)
            assert exc.value.status_code == 409
            await db.rollback()
            await db.refresh(user)
            with pytest.raises(HTTPException) as exc:
                await submit_avatar(AvatarIn(key='avatar/missing.png'), user, db)
            assert exc.value.status_code == 400
    finally:
        await engine.dispose()
