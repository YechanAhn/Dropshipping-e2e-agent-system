"""
Order Manager agent.

Owns the order-fulfillment lifecycle for the Naver SmartStore x AliExpress
dropshipping flow:

    poll_new_orders        -> watch Naver for paid orders, persist new ones
    prepare_fulfillment    -> build an AliExpress fulfillment draft (up to,
                              but never including, the payment step)
    confirm_payment_and_tracking
                           -> record the human-confirmed source order and sync
                              tracking back

Human-in-the-loop payment policy
--------------------------------
Payment is **never** automated.  ``prepare_fulfillment`` only prepares the
AliExpress order up to the payment step and parks the order in
``AWAITING_PAYMENT``.  An optional, dependency-injected ``SourceOrderPlacer``
may create the AliExpress cart/order draft and return its id, but it must stop
short of paying.  The actual payment is performed by a human operator, who then
calls ``confirm_payment_and_tracking``.

All external collaborators (repositories and the Naver Commerce client) are
dependency-injected so the agent can be exercised with in-memory fakes and no
network/database access.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from dropagent.utils.exceptions import DropAgentError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class OrderStatus(StrEnum):
    """Lifecycle states for a dropshipping order.

    Stored verbatim in :attr:`dropagent.db.models.order.Order.status`.
    """

    NEW = "NEW"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderProcessingError(DropAgentError):
    """Raised when an order cannot be processed (e.g. unmapped product)."""

    def __init__(
        self,
        message: str,
        naver_order_id: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        self.naver_order_id = naver_order_id
        error_details = dict(details or {})
        if naver_order_id:
            error_details["naver_order_id"] = naver_order_id
        super().__init__(message=message, details=error_details, original_error=original_error)


@dataclass
class FulfillmentDraft:
    """A prepared, *unpaid* AliExpress fulfillment for a Naver order.

    Represents everything needed to place the source order up to -- but not
    including -- the payment step.  ``needs_payment_approval`` defaults to
    ``True`` to make the human-in-the-loop payment gate explicit at every call
    site.

    Attributes:
        naver_order_id: The originating Naver SmartStore order id.
        source_product_id: The AliExpress product id to purchase.
        quantity: Units to order.
        shipping_address: Buyer shipping address (provider-specific shape).
        estimated_cost: Best-effort source cost estimate, if known.
        needs_payment_approval: Always ``True`` -- payment is manual.
    """

    naver_order_id: str
    source_product_id: str
    quantity: int
    shipping_address: dict[str, Any] = field(default_factory=dict)
    estimated_cost: Decimal | None = None
    needs_payment_approval: bool = True


# Pluggable hook that prepares an AliExpress order up to the payment step and
# returns the resulting source order id (or ``None`` for pure-manual mode).
# Implementations MUST NOT pay.
SourceOrderPlacer = Callable[[FulfillmentDraft], Awaitable[str | None]]


# Naver order status that signals "paid, ready to fulfill".
NAVER_PAID_STATUS = "PAYED"


def _first(raw: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-``None`` value among ``keys``.

    Naver order payloads vary in shape (top-level vs nested under
    ``productOrder``/``order``), so callers pass several candidate keys.
    """
    for key in keys:
        value = raw.get(key)
        if value is not None:
            return value
    return None


def _extract_order_fields(raw: dict[str, Any]) -> tuple[str | None, str | None, int, Decimal | None]:
    """Defensively pull ``(naver_order_id, product_id, quantity, total_price)``.

    Assumptions about the raw Naver order dict (keys are tried in order):
        - naver order id: ``productOrderId`` | ``orderId`` | ``id``
        - naver product id: ``productId`` | ``channelProductId`` | ``originProductNo``
        - quantity: ``quantity`` | ``orderQuantity`` (defaults to ``1``)
        - total price: ``totalPrice`` | ``totalPaymentAmount`` | ``totalProductAmount``

    A flattened ``data`` sub-dict (as some list endpoints wrap each row) is
    merged in so either shape resolves.  Missing identifiers come back as
    ``None`` and are handled by the caller.
    """
    merged: dict[str, Any] = {}
    for nested_key in ("data", "content", "productOrder", "order"):
        nested = raw.get(nested_key)
        if isinstance(nested, dict):
            merged.update(nested)
    merged.update(raw)  # top-level keys win over nested ones

    naver_order_id = _first(merged, "productOrderId", "orderId", "id")
    product_id = _first(merged, "productId", "channelProductId", "originProductNo")
    quantity_raw = _first(merged, "quantity", "orderQuantity")
    total_raw = _first(merged, "totalPrice", "totalPaymentAmount", "totalProductAmount")

    try:
        quantity = int(quantity_raw) if quantity_raw is not None else 1
    except (TypeError, ValueError):
        quantity = 1

    total_price: Decimal | None = None
    if total_raw is not None:
        try:
            total_price = Decimal(str(total_raw))
        except (InvalidOperation, TypeError, ValueError):
            total_price = None

    naver_order_id = str(naver_order_id) if naver_order_id is not None else None
    product_id = str(product_id) if product_id is not None else None
    return naver_order_id, product_id, quantity, total_price


class OrderManager:
    """Watches paid Naver orders and drives AliExpress fulfillment.

    Payment is human-in-the-loop: this agent never pays an AliExpress order.
    """

    def __init__(
        self,
        order_repo: Any,
        product_repo: Any,
        commerce_client: Any,
        *,
        source_order_placer: SourceOrderPlacer | None = None,
    ) -> None:
        """Wire up injected collaborators.

        Args:
            order_repo: ``OrderRepository``-shaped object.
            product_repo: ``ProductRepository``-shaped object.
            commerce_client: ``NaverCommerceClient``-shaped object.
            source_order_placer: Optional hook that prepares the AliExpress
                order up to payment and returns its id.  ``None`` (default)
                keeps source ordering fully manual.
        """
        self.order_repo = order_repo
        self.product_repo = product_repo
        self.commerce_client = commerce_client
        self.source_order_placer = source_order_placer

    async def poll_new_orders(self, from_date: str | None = None) -> list:
        """Fetch paid Naver orders and persist the ones we have not seen.

        Idempotent: any order whose ``naver_order_id`` already exists in the
        repository is skipped, so repeated polls never double-create.

        Args:
            from_date: Optional ISO-8601 start date forwarded to Naver.

        Returns:
            The list of newly created :class:`Order` rows (existing/unmappable
            orders are omitted).
        """
        raw_orders = await self.commerce_client.get_orders(status=NAVER_PAID_STATUS, from_date=from_date)
        logger.info("order_poll_fetched", count=len(raw_orders), from_date=from_date)

        created: list = []
        for raw in raw_orders:
            naver_order_id, product_id, quantity, total_price = _extract_order_fields(raw)

            if not naver_order_id:
                logger.warning("order_poll_missing_naver_id", raw=raw)
                continue

            existing = await self.order_repo.get_by_naver_id(naver_order_id)
            if existing is not None:
                logger.info("order_poll_skip_duplicate", naver_order_id=naver_order_id)
                continue

            if not product_id:
                logger.warning("order_poll_missing_product_id", naver_order_id=naver_order_id)
                continue

            product = await self.product_repo.get_by_naver_id(product_id)
            if product is None:
                logger.warning(
                    "order_poll_unmapped_product",
                    naver_order_id=naver_order_id,
                    naver_product_id=product_id,
                )
                continue

            order = await self.order_repo.create(
                {
                    "naver_order_id": naver_order_id,
                    "product_id": product.id,
                    "quantity": quantity,
                    "total_price": total_price if total_price is not None else Decimal("0"),
                    "status": OrderStatus.NEW.value,
                }
            )
            logger.info(
                "order_poll_created",
                order_id=order.id,
                naver_order_id=naver_order_id,
                product_id=product.id,
            )
            created.append(order)

        logger.info("order_poll_done", created=len(created), fetched=len(raw_orders))
        return created

    async def prepare_fulfillment(
        self,
        order: Any,
        shipping_address: dict[str, Any] | None = None,
    ) -> FulfillmentDraft:
        """Build an AliExpress fulfillment draft and park the order for payment.

        Resolves the source (AliExpress) product id from the mapped product,
        constructs a :class:`FulfillmentDraft`, optionally invokes the injected
        ``source_order_placer`` to create the source order *up to payment*, and
        moves the order to ``AWAITING_PAYMENT``.  Payment itself is left to a
        human operator.

        Args:
            order: The persisted order to fulfill (has ``id``, ``naver_order_id``,
                ``product_id``, ``quantity``, ``total_price``).
            shipping_address: Optional buyer shipping address to embed in the
                draft.

        Returns:
            The prepared :class:`FulfillmentDraft` (``needs_payment_approval`` is
            ``True``).

        Raises:
            OrderProcessingError: If the order's product cannot be resolved to an
                AliExpress product id.
        """
        product = await self.product_repo.get_by_id(order.product_id)
        if product is None or not getattr(product, "ali_product_id", None):
            raise OrderProcessingError(
                "Cannot resolve AliExpress product for order",
                naver_order_id=getattr(order, "naver_order_id", None),
                details={"product_id": getattr(order, "product_id", None)},
            )

        draft = FulfillmentDraft(
            naver_order_id=order.naver_order_id,
            source_product_id=str(product.ali_product_id),
            quantity=order.quantity,
            shipping_address=dict(shipping_address or {}),
            estimated_cost=getattr(order, "total_price", None),
            needs_payment_approval=True,
        )

        if self.source_order_placer is not None:
            # Hook prepares the source order up to -- never through -- payment.
            ali_order_id = await self.source_order_placer(draft)
            if ali_order_id:
                await self.order_repo.update_ali_order_id(order.id, ali_order_id)
                logger.info(
                    "order_source_draft_placed",
                    order_id=order.id,
                    ali_order_id=ali_order_id,
                )

        # Payment stays manual: park the order awaiting human payment approval.
        await self.order_repo.update_status(order.id, OrderStatus.AWAITING_PAYMENT.value)
        logger.info(
            "order_fulfillment_prepared",
            order_id=order.id,
            naver_order_id=order.naver_order_id,
            source_product_id=draft.source_product_id,
            needs_payment_approval=draft.needs_payment_approval,
        )
        return draft

    async def confirm_payment_and_tracking(
        self,
        order: Any,
        ali_order_id: str,
        tracking_no: str | None = None,
    ) -> None:
        """Record the human-confirmed source order and sync tracking.

        Called *after* a human has paid the AliExpress order.  Persists the
        AliExpress order id, advances status to ``ORDERED`` (or ``SHIPPED`` when
        a tracking number is supplied), and surfaces the tracking number.

        The injected commerce client exposes no tracking-update endpoint, so the
        tracking number is logged rather than pushed; if a future client gains a
        suitable method it is invoked, otherwise this degrades gracefully.

        Args:
            order: The persisted order being confirmed.
            ali_order_id: The AliExpress order id created during the human
                payment step.
            tracking_no: Optional carrier tracking number.
        """
        await self.order_repo.update_ali_order_id(order.id, ali_order_id)

        new_status = OrderStatus.SHIPPED if tracking_no else OrderStatus.ORDERED
        await self.order_repo.update_status(order.id, new_status.value)

        if tracking_no:
            # The Naver Commerce client has no tracking-dispatch method; only
            # call one if a compatible client provides it, else log it.
            dispatch = getattr(self.commerce_client, "dispatch_order", None)
            if callable(dispatch):
                await dispatch(order.naver_order_id, tracking_no)
                logger.info(
                    "order_tracking_dispatched",
                    order_id=order.id,
                    tracking_no=tracking_no,
                )
            else:
                logger.info(
                    "order_tracking_recorded",
                    order_id=order.id,
                    naver_order_id=order.naver_order_id,
                    tracking_no=tracking_no,
                    note="commerce client has no tracking-dispatch method",
                )

        logger.info(
            "order_payment_confirmed",
            order_id=order.id,
            ali_order_id=ali_order_id,
            status=new_status.value,
            has_tracking=tracking_no is not None,
        )
