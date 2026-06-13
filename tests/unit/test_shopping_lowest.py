"""Unit tests for NaverShoppingClient.get_catalog_lowest (최저가 조회)."""

import pytest

from dropagent.clients.naver.shopping_api import CatalogLowest, NaverShoppingClient


class _FakeResp:
    status_code = 200
    text = ""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeHttp:
    """Minimal async httpx stand-in returning a fixed Shopping API payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.is_closed = False
        self.last_params: dict | None = None

    async def get(self, url, params=None, headers=None):  # noqa: ANN001
        self.last_params = params
        return _FakeResp(self._payload)

    async def aclose(self) -> None:
        self.is_closed = True


def _payload(items: list[dict], total: int) -> dict:
    return {"items": items, "total": total, "start": 1, "display": len(items)}


async def test_get_catalog_lowest_splits_floor_and_badge():
    """lowest_price = overall floor (incl 단독); catalog_parent_price = badge price."""
    items = [
        {"lprice": "15000", "productType": 2, "mallName": "단독몰"},  # cheapest overall (standalone)
        {"lprice": "18000", "productType": 1, "mallName": "카탈로그A"},  # catalog parent (badge)
        {"lprice": "22000", "productType": 1, "mallName": "카탈로그B"},
    ]
    client = NaverShoppingClient(http_client=_FakeHttp(_payload(items, total=3)))

    res = await client.get_catalog_lowest("골전도 이어폰")

    assert isinstance(res, CatalogLowest)
    assert res.lowest_price == 15000  # overall market floor
    assert res.catalog_parent_price == 18000  # cheapest 가격비교 대표 = 최저가 badge
    assert res.has_catalog is True
    assert res.mall_name == "단독몰"  # who holds the overall lowest
    assert res.total == 3


async def test_get_catalog_lowest_uses_sort_asc():
    """The single call must request sort=asc (cheapest first)."""
    http = _FakeHttp(_payload([{"lprice": "9900", "productType": 2}], total=1))
    client = NaverShoppingClient(http_client=http)

    await client.get_catalog_lowest("키워드")

    assert http.last_params is not None
    assert http.last_params.get("sort") == "asc"


async def test_get_catalog_lowest_no_catalog():
    """When only 단독 listings exist, catalog_parent_price is None / has_catalog False."""
    items = [
        {"lprice": "12000", "productType": 2},
        {"lprice": "13000", "productType": 2},
    ]
    client = NaverShoppingClient(http_client=_FakeHttp(_payload(items, total=2)))

    res = await client.get_catalog_lowest("단독상품")

    assert res.lowest_price == 12000
    assert res.catalog_parent_price is None
    assert res.has_catalog is False


async def test_get_catalog_lowest_empty():
    """No results -> an all-zero snapshot (no crash)."""
    client = NaverShoppingClient(http_client=_FakeHttp(_payload([], total=0)))

    res = await client.get_catalog_lowest("없는키워드")

    assert res.lowest_price == 0
    assert res.catalog_parent_price is None
    assert res.has_catalog is False


@pytest.mark.parametrize(
    ("product_type", "is_catalog", "is_standalone"),
    [(1, True, False), (2, False, True), (4, True, False), (11, False, True), (3, False, False)],
)
def test_item_type_helpers(product_type, is_catalog, is_standalone):
    from dropagent.clients.naver.models import NaverShoppingItem

    item = NaverShoppingItem(lowest_price=1000, product_type=product_type)
    assert item.is_catalog is is_catalog
    assert item.is_standalone is is_standalone
