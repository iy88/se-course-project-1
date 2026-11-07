"""Regression coverage for admin case-claim synchronization, list filters, and stats parameter validation.

Covers: claiming a report case syncs report.status=processing in the same transaction;
claiming a non-report case leaves reports untouched; mine=true returns only the caller's
claimed cases; report lists filter by target_type; invalid /admin/stats date parameters
return 422 rather than 500.
"""

import pytest
from app.api.v1.admin.cases import claim_case, list_cases
from app.api.v1.admin.reports import list_reports
from app.api.v1.admin.stats import stats
from app.db.session import Base
from app.models import DisposalCase, Report, User
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.mark.asyncio
async def test_claim_report_case_syncs_processing(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "cases.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin1 = User(email='admin1@example.com', display_name='A1', password_hash='x', role='admin')
            admin2 = User(email='admin2@example.com', display_name='A2', password_hash='x', role='admin')
            reporter = User(email='r@example.com', display_name='R', password_hash='x')
            db.add_all([admin1, admin2, reporter])
            await db.commit()
            report = Report(reporter_id=reporter.id, target_type='product', target_id=1, reason='违规')
            db.add(report)
            await db.commit()
            case = DisposalCase(case_type='report', title='举报事项', report_id=report.id)
            db.add(case)
            await db.commit()

            out = await list_cases(admin2, db, page=1, page_size=20, case_status='processing', case_type=None, mine=True)
            assert out['items'] == [] and out['total'] == 0

            await claim_case(case.id, admin1, db)
            await db.refresh(case)
            await db.refresh(report)
            assert case.status == 'processing' and case.claimed_by_id == admin1.id
            assert report.status == 'processing'

            mine_processing = await list_cases(admin1, db, page=1, page_size=20, case_status='processing', case_type=None, mine=True)
            assert [c['id'] for c in mine_processing['items']] == [case.id]
            mine_all = await list_cases(admin1, db, page=1, page_size=20, case_status='all', case_type=None, mine=True)
            assert [c['id'] for c in mine_all['items']] == [case.id] and mine_all['total'] == 1
            mine_pending = await list_cases(admin1, db, page=1, page_size=20, case_status='pending', case_type=None, mine=True)
            assert mine_pending['items'] == []
            other_mine = await list_cases(admin2, db, page=1, page_size=20, case_status='all', case_type=None, mine=True)
            assert other_mine['items'] == []
            shared = await list_cases(admin2, db, page=1, page_size=20, case_status='processing', case_type=None, mine=False)
            assert [c['id'] for c in shared['items']] == [case.id]

            # A second admin claim is rejected, and the report status is neither rolled back nor changed twice.
            with pytest.raises(HTTPException) as exc:
                await claim_case(case.id, admin2, db)
            assert exc.value.status_code == 409
            await db.rollback()
            await db.refresh(report)
            assert report.status == 'processing'
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_claim_non_report_case_leaves_reports(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "cases2.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin = User(email='admin@example.com', display_name='A', password_hash='x', role='admin')
            reporter = User(email='r@example.com', display_name='R', password_hash='x')
            db.add_all([admin, reporter])
            await db.commit()
            report = Report(reporter_id=reporter.id, target_type='comment', target_id=9, reason='spam')
            db.add(report)
            product_review = DisposalCase(case_type='product_review', title='商品审核')
            db.add(product_review)
            await db.commit()

            await claim_case(product_review.id, admin, db)
            await db.refresh(product_review)
            await db.refresh(report)
            assert product_review.status == 'processing'
            # Claiming a case with no linked report does not affect any report status.
            assert report.status == 'pending'
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stats_invalid_date_returns_422(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "stats.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin = User(email='admin@example.com', display_name='A', password_hash='x', role='admin')
            db.add(admin)
            await db.commit()

            for bad_from, bad_to in [('2026-13-01', None), ('not-a-date', None), (None, '2026/11/01')]:
                with pytest.raises(HTTPException) as exc:
                    await stats(admin, db, date_from=bad_from, date_to=bad_to)
                assert exc.value.status_code == 422

            result = await stats(admin, db, date_from='2026-11-01', date_to='2026-11-01')
            assert result['range'] == {'from': '2026-11-01', 'to': '2026-11-01', 'completed_trades': 0}
            result = await stats(admin, db, date_from=None, date_to=None)
            assert result['range']['completed_trades'] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_reports_filters_by_target_type(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "reports.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin = User(email='admin@example.com', display_name='A', password_hash='x', role='admin')
            reporter = User(email='r@example.com', display_name='R', password_hash='x')
            db.add_all([admin, reporter])
            await db.commit()
            db.add_all([
                Report(reporter_id=reporter.id, target_type='product', target_id=1, reason='p'),
                Report(reporter_id=reporter.id, target_type='comment', target_id=2, reason='c'),
                Report(reporter_id=reporter.id, target_type='product', target_id=3, reason='p2'),
            ])
            await db.commit()

            products = await list_reports(admin, db, page=1, page_size=20, report_status='all', target_type='product')
            assert [r['target_id'] for r in products['items']] == [3, 1] and products['total'] == 2
            comments = await list_reports(admin, db, page=1, page_size=20, report_status='all', target_type='comment')
            assert [r['target_id'] for r in comments['items']] == [2]
            everything = await list_reports(admin, db, page=1, page_size=20, report_status='all', target_type=None)
            assert len(everything['items']) == 3
            pending = await list_reports(admin, db, page=1, page_size=20, report_status='pending', target_type='product')
            assert [r['target_id'] for r in pending['items']] == [3, 1]
    finally:
        await engine.dispose()
