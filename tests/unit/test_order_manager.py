"""
Unit tests for the :mod:`dropagent.agents.order_manager` agent.

All external collaborators (order/product repositories and the Naver Commerce
client) are replaced with small in-memory fakes so the suite runs with no
database and no network access.  The fakes implement only the surface the
``OrderManager`` relies on:

    - commerce_client.get_orders(status, from_date) -> list[dict]
    - order_repo.get_by_naver_id / get_by_id / create / update_status /
      update_ali_order_id
    - product_repo.get_by_naver_id / get_by_id

The tests focus on the human-in-the-loop payment policy: orders are watched
and persisted idempotently, a fulfillment draft is prepared *up to* (never
through) payment, and the source order is recorded only after a human confirms.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from dropagent.agents.order_manager import (
    FulfillmentDraft,
    OrderManager,
    OrderStatus,
)

# =====================================================================
# Test doubles (no DB, no network)
# =====================================================================


@dataclass
class FakeOrder:
    """Minimal stand-in for ``dropagent.db.models.order.Order``."""

    id: int
    naver_order_id: str
    product_id: int
    quantity: int
    total_price: Decimal
    status: str
    ali_order_id: str | None = None


@dataclass
class FakeProduct:
    """Minimal stand-in for ``dropagent.db.models.product.Product``."""

    id: int
    naver_product_id: str
    ali_product_id: str


class FakeOrderRepository:
    """In-memory ``OrderRepository`` exposing only the used methods."""

    def __init__(self, orders: list[FakeOrder] | None = None) -> None:
        self.orders: dict[int, FakeOrder] = {o.id: o for o in (orders or [])}
        self._next_id = (max(self.orders, default=0)) + 1
        self.created: list[FakeOrder] = []
        # Call log for asserting no surprise side effects.
        self.status_updates: list[tuple[int, str]] = []
        self.ali_id_updates: list[tuple[int, str]] = []

    async def get_by_naver_id(self, naver_order_id: str) -> FakeOrder | None:
        for order in self.orders.values():
            if order.naver_order_id == naver_order_id:
                return order
        return None

    async def get_by_id(self, order_id: int) -> FakeOrder | None:
        return self.orders.get(order_id)

    async def create(self, data: dict[str, Any]) -> FakeOrder:
        order = FakeOrder(
            id=self._next_id,
            naver_order_id=data["naver_order_id"],
            product_id=data["product_id"],
            quantity=data["quantity"],
            total_price=data["total_price"],
            status=data["status"],
        )
        self._next_id += 1
        self.orders[order.id] = order
        self.created.append(order)
        return order

    async def update_status(self, order_id: int, status: str) -> FakeOrder:
        order = self.orders[order_id]
        order.status = status
        self.status_updates.append((order_id, status))
        return order

    async def update_ali_order_id(self, order_id: int, ali_order_id: str) -> FakeOrder:
        order = self.orders[order_id]
        order.ali_order_id = ali_order_id
        self.ali_id_updates.append((order_id, ali_order_id))
        return order


class FakeProductRepository:
    """In-memory ``ProductRepository`` exposing only the used methods."""

    def __init__(self, products: list[FakeProduct] | None = None) -> None:
        self.products: dict[int, FakeProduct] = {p.id: p for p in (products or [])}

    async def get_by_naver_id(self, naver_product_id: str) -> FakeProduct | None:
        for product in self.products.values():
            if product.naver_product_id == naver_product_id:
                return product
        return None

    async def get_by_id(self, product_id: int) -> FakeProduct | None:
        return self.products.get(product_id)


class FakeCommerceClient:
    """Async Naver Commerce client returning a fixed list of raw orders."""

    def __init__(self, raw_orders: list[dict[str, Any]]) -> None:
        self._raw_orders = raw_orders
        self.calls: list[dict[str, Any]] = []

    async def get_orders(
        self,
        status: str | None = None,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append({"status": status, "from_date": from_date})
        return list(self._raw_orders)


class TrackingCommerceClient(FakeCommerceClient):
    """Commerce client that *does* expose a tracking-dispatch endpoint."""

    def __init__(self, raw_orders: list[dict[str, Any]] | None = None) -> None:
        super().__init__(raw_orders or [])
        self.dispatched: list[tuple[str, str]] = []

    async def dispatch_order(self, naver_order_id: str, tracking_no: str) -> None:
        self.dispatched.append((naver_order_id, tracking_no))


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def mapped_product() -> FakeProduct:
    """A product mapping Naver product ``NP-1`` -> AliExpress ``ALI-100``."""
    return FakeProduct(id=10, naver_product_id="NP-1", ali_product_id="ALI-100")


@pytest.fixture
def existing_order(mapped_product: FakeProduct) -> FakeOrder:
    """An order that was already persisted on a previous poll."""
    return FakeOrder(
        id=1,
        naver_order_id="NO-EXISTING",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.NEW.value,
    )


@pytest.fixture
def raw_payed_orders() -> list[dict[str, Any]]:
    """Two raw PAYED Naver orders: one new, one already persisted."""
    return [
        {
            "productOrderId": "NO-NEW",
            "productId": "NP-1",
            "quantity": 2,
            "totalPrice": "39800",
        },
        {
            "productOrderId": "NO-EXISTING",
            "productId": "NP-1",
            "quantity": 1,
            "totalPrice": "19900",
        },
    ]


# =====================================================================
# poll_new_orders
# =====================================================================


async def test_poll_creates_only_new_order_and_dedupes_existing(
    raw_payed_orders: list[dict[str, Any]],
    mapped_product: FakeProduct,
    existing_order: FakeOrder,
) -> None:
    """Polling persists only the unseen order; the known one is skipped."""
    order_repo = FakeOrderRepository(orders=[existing_order])
    product_repo = FakeProductRepository(products=[mapped_product])
    commerce = FakeCommerceClient(raw_payed_orders)
    manager = OrderManager(order_repo, product_repo, commerce)

    created = await manager.poll_new_orders(from_date="2026-06-01")

    # Only the new order is created; the existing one is deduped.
    assert len(created) == 1
    new_order = created[0]
    assert new_order.naver_order_id == "NO-NEW"
    assert new_order.product_id == mapped_product.id
    assert new_order.quantity == 2
    assert new_order.total_price == Decimal("39800")
    assert new_order.status == OrderStatus.NEW.value

    # Repository observed exactly one create call.
    assert len(order_repo.created) == 1

    # The commerce client was queried for PAYED orders with the from_date.
    assert commerce.calls == [{"status": "PAYED", "from_date": "2026-06-01"}]


async def test_poll_is_idempotent_across_repeated_calls(
    raw_payed_orders: list[dict[str, Any]],
    mapped_product: FakeProduct,
    existing_order: FakeOrder,
) -> None:
    """A second identical poll creates nothing (idempotency)."""
    order_repo = FakeOrderRepository(orders=[existing_order])
    product_repo = FakeProductRepository(products=[mapped_product])
    commerce = FakeCommerceClient(raw_payed_orders)
    manager = OrderManager(order_repo, product_repo, commerce)

    first = await manager.poll_new_orders()
    second = await manager.poll_new_orders()

    assert len(first) == 1
    assert second == []
    assert len(order_repo.created) == 1


async def test_poll_skips_unmapped_products(
    mapped_product: FakeProduct,
) -> None:
    """Orders whose Naver product has no mapping are not persisted."""
    order_repo = FakeOrderRepository()
    product_repo = FakeProductRepository(products=[mapped_product])
    commerce = FakeCommerceClient(
        [{"productOrderId": "NO-ORPHAN", "productId": "NP-UNKNOWN", "quantity": 1, "totalPrice": "1000"}]
    )
    manager = OrderManager(order_repo, product_repo, commerce)

    created = await manager.poll_new_orders()

    assert created == []
    assert order_repo.created == []


async def test_poll_extracts_alternate_key_shapes(
    mapped_product: FakeProduct,
) -> None:
    """Defensive extraction handles nested + alternate raw key names."""
    order_repo = FakeOrderRepository()
    product_repo = FakeProductRepository(products=[mapped_product])
    # Nested under ``content`` with alternate id/qty/price keys.
    commerce = FakeCommerceClient(
        [
            {
                "content": {
                    "orderId": "NO-ALT",
                    "channelProductId": "NP-1",
                    "orderQuantity": 3,
                    "totalPaymentAmount": 5970,
                }
            }
        ]
    )
    manager = OrderManager(order_repo, product_repo, commerce)

    created = await manager.poll_new_orders()

    assert len(created) == 1
    assert created[0].naver_order_id == "NO-ALT"
    assert created[0].quantity == 3
    assert created[0].total_price == Decimal("5970")


# =====================================================================
# prepare_fulfillment  (human-in-the-loop payment gate)
# =====================================================================


async def test_prepare_fulfillment_builds_draft_and_parks_for_payment(
    mapped_product: FakeProduct,
) -> None:
    """A draft is produced, the order is parked AWAITING_PAYMENT, no auto-pay."""
    order = FakeOrder(
        id=5,
        naver_order_id="NO-NEW",
        product_id=mapped_product.id,
        quantity=2,
        total_price=Decimal("39800"),
        status=OrderStatus.NEW.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])
    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]))

    draft = await manager.prepare_fulfillment(order, shipping_address={"name": "Buyer", "zip": "06236"})

    assert isinstance(draft, FulfillmentDraft)
    assert draft.naver_order_id == "NO-NEW"
    assert draft.source_product_id == "ALI-100"  # resolved AliExpress id
    assert draft.quantity == 2
    assert draft.shipping_address == {"name": "Buyer", "zip": "06236"}
    assert draft.estimated_cost == Decimal("39800")

    # The payment gate is explicit and always on.
    assert draft.needs_payment_approval is True

    # Order is parked awaiting human payment -- and NOT auto-advanced past it.
    assert order.status == OrderStatus.AWAITING_PAYMENT.value
    assert order_repo.status_updates == [(5, OrderStatus.AWAITING_PAYMENT.value)]

    # No source order id was set because no placer is configured, and crucially
    # the order never reaches ORDERED/SHIPPED without human confirmation.
    assert order.ali_order_id is None
    assert order_repo.ali_id_updates == []


async def test_prepare_fulfillment_default_is_pure_manual(
    mapped_product: FakeProduct,
) -> None:
    """With no placer, no AliExpress order id is recorded (pure manual mode)."""
    order = FakeOrder(
        id=6,
        naver_order_id="NO-MANUAL",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.NEW.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])
    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]))

    draft = await manager.prepare_fulfillment(order)

    assert draft.needs_payment_approval is True
    assert draft.shipping_address == {}
    assert order_repo.ali_id_updates == []
    assert order.status == OrderStatus.AWAITING_PAYMENT.value


async def test_prepare_fulfillment_placer_drafts_up_to_payment(
    mapped_product: FakeProduct,
) -> None:
    """A configured placer drafts the source order (id stored) but never pays."""
    order = FakeOrder(
        id=7,
        naver_order_id="NO-PLACER",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.NEW.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])

    seen_drafts: list[FulfillmentDraft] = []

    async def placer(draft: FulfillmentDraft) -> str:
        """Prepare the AliExpress order up to payment; return its draft id."""
        seen_drafts.append(draft)
        return "ALI-ORDER-DRAFT-1"

    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]), source_order_placer=placer)

    draft = await manager.prepare_fulfillment(order)

    # The placer received the draft and its returned id was persisted.
    assert seen_drafts == [draft]
    assert order.ali_order_id == "ALI-ORDER-DRAFT-1"
    assert order_repo.ali_id_updates == [(7, "ALI-ORDER-DRAFT-1")]

    # Even with a placer, payment stays manual: status is AWAITING_PAYMENT only.
    assert draft.needs_payment_approval is True
    assert order.status == OrderStatus.AWAITING_PAYMENT.value
    assert OrderStatus.ORDERED.value not in [s for _, s in order_repo.status_updates]


async def test_prepare_fulfillment_placer_returning_none_records_no_ali_id(
    mapped_product: FakeProduct,
) -> None:
    """A placer may return None (nothing drafted); no ali id is recorded."""
    order = FakeOrder(
        id=8,
        naver_order_id="NO-PLACER-NONE",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.NEW.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])

    async def placer(draft: FulfillmentDraft) -> None:
        return None

    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]), source_order_placer=placer)

    await manager.prepare_fulfillment(order)

    assert order.ali_order_id is None
    assert order_repo.ali_id_updates == []
    assert order.status == OrderStatus.AWAITING_PAYMENT.value


async def test_prepare_fulfillment_raises_for_unresolvable_product() -> None:
    """If the product has no AliExpress id, preparation fails loudly."""
    bad_product = FakeProduct(id=20, naver_product_id="NP-9", ali_product_id="")
    order = FakeOrder(
        id=9,
        naver_order_id="NO-BAD",
        product_id=bad_product.id,
        quantity=1,
        total_price=Decimal("100"),
        status=OrderStatus.NEW.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[bad_product])
    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]))

    with pytest.raises(Exception):  # noqa: B017 - OrderProcessingError subclass
        await manager.prepare_fulfillment(order)

    # The order was not parked / advanced when preparation could not complete.
    assert order_repo.status_updates == []


# =====================================================================
# confirm_payment_and_tracking  (post human payment)
# =====================================================================


async def test_confirm_payment_records_ali_id_and_sets_ordered(
    mapped_product: FakeProduct,
) -> None:
    """Without tracking, confirmation records the ali id and sets ORDERED."""
    order = FakeOrder(
        id=11,
        naver_order_id="NO-CONFIRM",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.AWAITING_PAYMENT.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])
    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]))

    await manager.confirm_payment_and_tracking(order, ali_order_id="ALI-ORDER-99")

    assert order.ali_order_id == "ALI-ORDER-99"
    assert order_repo.ali_id_updates == [(11, "ALI-ORDER-99")]
    assert order.status == OrderStatus.ORDERED.value


async def test_confirm_payment_with_tracking_sets_shipped_and_dispatches(
    mapped_product: FakeProduct,
) -> None:
    """With tracking, status becomes SHIPPED and a tracking-capable client is used."""
    order = FakeOrder(
        id=12,
        naver_order_id="NO-SHIP",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.AWAITING_PAYMENT.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])
    commerce = TrackingCommerceClient()
    manager = OrderManager(order_repo, product_repo, commerce)

    await manager.confirm_payment_and_tracking(order, ali_order_id="ALI-ORDER-77", tracking_no="TRK-555")

    assert order.ali_order_id == "ALI-ORDER-77"
    assert order.status == OrderStatus.SHIPPED.value
    # Tracking dispatched through the client's real method (not invented).
    assert commerce.dispatched == [("NO-SHIP", "TRK-555")]


async def test_confirm_payment_with_tracking_logs_when_client_lacks_dispatch(
    mapped_product: FakeProduct,
) -> None:
    """A client without a dispatch method degrades gracefully (no crash)."""
    order = FakeOrder(
        id=13,
        naver_order_id="NO-NODISPATCH",
        product_id=mapped_product.id,
        quantity=1,
        total_price=Decimal("19900"),
        status=OrderStatus.AWAITING_PAYMENT.value,
    )
    order_repo = FakeOrderRepository(orders=[order])
    product_repo = FakeProductRepository(products=[mapped_product])
    # Plain client (no ``dispatch_order``) -- must not raise.
    manager = OrderManager(order_repo, product_repo, FakeCommerceClient([]))

    await manager.confirm_payment_and_tracking(order, ali_order_id="ALI-ORDER-88", tracking_no="TRK-001")

    assert order.ali_order_id == "ALI-ORDER-88"
    assert order.status == OrderStatus.SHIPPED.value


# =====================================================================
# Public API surface / types
# =====================================================================


async def test_fulfillment_draft_defaults() -> None:
    """``FulfillmentDraft`` defaults: empty address, payment-approval gate on."""
    draft = FulfillmentDraft(naver_order_id="X", source_product_id="ALI-1", quantity=1)
    assert draft.shipping_address == {}
    assert draft.estimated_cost is None
    assert draft.needs_payment_approval is True


async def test_order_status_members_are_strenum() -> None:
    """``OrderStatus`` is a StrEnum with the documented members."""
    assert OrderStatus.NEW == "NEW"
    assert OrderStatus.AWAITING_PAYMENT == "AWAITING_PAYMENT"
    assert OrderStatus.ORDERED == "ORDERED"
    assert OrderStatus.SHIPPED == "SHIPPED"
    assert OrderStatus.DELIVERED == "DELIVERED"
    assert OrderStatus.CANCELLED == "CANCELLED"
    assert {s.value for s in OrderStatus} == {
        "NEW",
        "AWAITING_PAYMENT",
        "ORDERED",
        "SHIPPED",
        "DELIVERED",
        "CANCELLED",
    }
