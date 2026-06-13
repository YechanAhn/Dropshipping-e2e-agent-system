"""
Unit tests for the DropAgent FastAPI HTTP API.

These tests exercise the app built by :func:`dropagent.api.app.create_app`
without any real database. The repository factory dependencies
(``get_product_repo`` / ``get_order_repo`` / ``get_analytics_repo``) are
replaced via ``app.dependency_overrides`` with in-memory fakes, and requests
are driven through ``httpx.ASGITransport`` so no network/socket is involved.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from dropagent.api.app import create_app
from dropagent.api.deps import (
    get_analytics_repo,
    get_order_repo,
    get_product_repo,
)
from dropagent.db.models import Order, Product

# ─── In-memory fakes ────────────────────────────────────────────────────


class FakeProductRepository:
    """In-memory stand-in for ProductRepository (only routed methods)."""

    def __init__(self, products: list[Product]) -> None:
        self._products: dict[int, Product] = {p.id: p for p in products}

    async def list_all(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Product]:
        items = list(self._products.values())
        if status is not None:
            items = [p for p in items if p.status == status]
        return items[offset : offset + limit]

    async def get_by_id(self, product_id: int) -> Product | None:
        return self._products.get(product_id)

    async def update_status(self, product_id: int, status: str) -> Product:
        product = self._products[product_id]
        product.status = status
        return product


class FakeOrderRepository:
    """In-memory stand-in for OrderRepository (only routed methods)."""

    def __init__(self, orders: list[Order]) -> None:
        self._orders: dict[int, Order] = {o.id: o for o in orders}

    async def list_by_status(self, status: str, limit: int = 100) -> list[Order]:
        return [o for o in self._orders.values() if o.status == status][:limit]

    async def list_recent(self, hours: int = 24, limit: int = 100) -> list[Order]:
        return list(self._orders.values())[:limit]

    async def get_by_id(self, order_id: int) -> Order | None:
        return self._orders.get(order_id)

    async def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for order in self._orders.values():
            counts[order.status] = counts.get(order.status, 0) + 1
        return counts

    async def get_revenue_summary(self, days: int = 30) -> dict:
        total = sum(float(o.total_price) for o in self._orders.values())
        count = len(self._orders)
        return {
            "total_revenue": total,
            "total_orders": count,
            "avg_order_value": (total / count) if count else 0.0,
        }


class FakeAnalyticsRepository:
    """In-memory stand-in for AnalyticsRepository (only routed methods)."""

    def __init__(self, keywords: list[dict]) -> None:
        self._keywords = keywords

    async def get_top_trending_keywords(self, limit: int = 20) -> list[dict]:
        return self._keywords[:limit]


# ─── Fixtures ───────────────────────────────────────────────────────────


def _make_product(product_id: int, status: str) -> Product:
    return Product(
        id=product_id,
        ali_product_id=f"ALI-{product_id}",
        naver_product_id=None,
        product_name_en=f"Test Product {product_id}",
        product_name_ko=f"테스트 상품 {product_id}",
        category_ali="Electronics",
        category_naver="디지털/가전",
        price_ali=Decimal("15000.00"),  # AliExpress price already in KRW (target_currency=KRW)
        price_naver=Decimal("19900.00"),
        margin_rate=Decimal("30.00"),
        priority_score=Decimal("80.00"),
        risk_score=Decimal("20.00"),
        ops_cost_score=Decimal("15.00"),
        demand_score=Decimal("70.00"),
        status=status,
    )


def _make_order(order_id: int, status: str) -> Order:
    now = datetime.now(UTC)
    order = Order(
        id=order_id,
        naver_order_id=f"NAVER-{order_id}",
        ali_order_id=None,
        product_id=1,
        quantity=2,
        total_price=Decimal("39800.00"),
        status=status,
    )
    # TimestampMixin columns are DB-populated; set explicitly for serialization.
    order.created_at = now
    order.updated_at = now
    return order


@pytest.fixture
def products() -> list[Product]:
    return [_make_product(1, "pending"), _make_product(2, "approved")]


@pytest.fixture
def orders() -> list[Order]:
    return [_make_order(1, "new"), _make_order(2, "shipped")]


@pytest.fixture
def keywords() -> list[dict]:
    return [
        {
            "keyword": "ring light",
            "category": "Electronics",
            "total_search_volume": 12000,
            "avg_click_ratio": 0.45,
            "record_count": 5,
        }
    ]


@pytest.fixture
def app(products: list[Product], orders: list[Order], keywords: list[dict]):
    application = create_app()
    application.dependency_overrides[get_product_repo] = lambda: FakeProductRepository(products)
    application.dependency_overrides[get_order_repo] = lambda: FakeOrderRepository(orders)
    application.dependency_overrides[get_analytics_repo] = lambda: FakeAnalyticsRepository(keywords)
    return application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ─── Tests ──────────────────────────────────────────────────────────────


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_list_products_returns_fakes(client: httpx.AsyncClient) -> None:
    resp = await client.get("/products/")
    assert resp.status_code == 200
    body = resp.json()
    assert {p["id"] for p in body} == {1, 2}
    assert {p["ali_product_id"] for p in body} == {"ALI-1", "ALI-2"}


async def test_list_products_filtered_by_status(client: httpx.AsyncClient) -> None:
    resp = await client.get("/products/", params={"status": "approved"})
    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [2]
    assert body[0]["status"] == "approved"


async def test_get_product_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/products/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 1
    # ALI price arrives already in KRW (target_currency=KRW); price_ali_krw mirrors it.
    assert float(body["price_ali"]) == 15000.0
    assert float(body["price_ali_krw"]) == 15000.0


async def test_get_product_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.get("/products/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Product not found"


async def test_approve_product_flips_status(client: httpx.AsyncClient) -> None:
    resp = await client.post("/products/1/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # The change is reflected on a subsequent read.
    follow = await client.get("/products/1")
    assert follow.json()["status"] == "approved"


async def test_reject_product_flips_status(client: httpx.AsyncClient) -> None:
    resp = await client.post("/products/2/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


async def test_approve_product_not_found(client: httpx.AsyncClient) -> None:
    resp = await client.post("/products/999/approve")
    assert resp.status_code == 404


async def test_list_orders_recent_default(client: httpx.AsyncClient) -> None:
    resp = await client.get("/orders/")
    assert resp.status_code == 200
    body = resp.json()
    assert {o["id"] for o in body} == {1, 2}


async def test_list_orders_by_status(client: httpx.AsyncClient) -> None:
    resp = await client.get("/orders/", params={"status": "shipped"})
    assert resp.status_code == 200
    body = resp.json()
    assert [o["id"] for o in body] == [2]


async def test_get_order_found_and_missing(client: httpx.AsyncClient) -> None:
    found = await client.get("/orders/1")
    assert found.status_code == 200
    assert found.json()["naver_order_id"] == "NAVER-1"

    missing = await client.get("/orders/999")
    assert missing.status_code == 404


async def test_analytics_summary_has_three_keys(client: httpx.AsyncClient) -> None:
    resp = await client.get("/analytics/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"revenue_summary", "order_counts", "top_trending_keywords"}
    assert body["revenue_summary"]["total_orders"] == 2
    assert body["order_counts"] == {"new": 1, "shipped": 1}
    assert body["top_trending_keywords"][0]["keyword"] == "ring light"


async def test_settings_get_and_put(client: httpx.AsyncClient) -> None:
    get_resp = await client.get("/settings/")
    assert get_resp.status_code == 200
    current = get_resp.json()
    assert "scoring_weights" in current
    assert "automation_flags" in current

    current["automation_flags"]["auto_approve"] = True
    put_resp = await client.put("/settings/", json=current)
    assert put_resp.status_code == 200
    assert put_resp.json()["automation_flags"]["auto_approve"] is True


async def test_cors_allows_dashboard_origin():
    """The Next.js dashboard origin is allowed by CORS."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
