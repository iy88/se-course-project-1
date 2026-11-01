"""商品响应与匿名处置提示回归，不访问外部服务。"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import products


@pytest.mark.asyncio
async def test_product_response_without_restriction():
    product = SimpleNamespace(
        id=1, seller_id=1, display_restricted=False, title='教材', description='说明',
        price_cents=100, status='listed', display_restricted_reason=None,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    with patch.object(products, 'get_storage', return_value=Mock()), patch.object(
        products.product_service, 'load_product_images', new=AsyncMock(return_value=[])
    ), patch.object(products.product_service, 'load_product_tags', new=AsyncMock(return_value=[])):
        result = await products._out(AsyncMock(), product, SimpleNamespace(id=2))
    assert result.id == 1
    assert result.restriction_result is None


@pytest.mark.asyncio
@pytest.mark.parametrize('restricted,confirmed,status,visible', [
    (True, True, 'handled', True), (False, True, 'handled', False),
    (True, False, 'handled', False), (True, True, 'unfounded', False),
])
async def test_public_notice_whitelist(restricted, confirmed, status, visible):
    product = SimpleNamespace(display_restricted=restricted, display_restricted_case_id=3)
    db = AsyncMock()
    db.get.side_effect = [product, SimpleNamespace(report_id=4), SimpleNamespace(
        result_confirmed=confirmed, status=status, public_result='违规商品已停止公开',
    )]
    if visible:
        assert await products.restriction_result(1, SimpleNamespace(id=2), db) == {
            'public_result': '违规商品已停止公开',
        }
    else:
        with pytest.raises(HTTPException) as exc:
            await products.restriction_result(1, SimpleNamespace(id=2), db)
        assert exc.value.status_code == 404
