"""
DS-backed source-order placer for the OrderManager.

Adapts the AliExpress DS ``place_order`` to the ``SourceOrderPlacer`` hook
(``FulfillmentDraft -> ali_order_id | None``). It CREATES an (unpaid) AliExpress
order obligation; it NEVER pays -- payment stays a human-gated step
(``OrderManager.confirm_payment_and_tracking``). This placer should only be
injected into the OrderManager when the operator explicitly opts in
(``ALI_AUTO_ORDER``), since placing an order is a real outward action.
"""

from __future__ import annotations

from dropagent.agents.order_manager import FulfillmentDraft, SourceOrderPlacer
from dropagent.clients.aliexpress.ds_api import AliExpressDSClient
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


def make_ds_source_order_placer(client: AliExpressDSClient) -> SourceOrderPlacer:
    """Build a SourceOrderPlacer that creates (does NOT pay) AliExpress orders.

    The returned coroutine maps a :class:`FulfillmentDraft` to a single
    ``product_items`` entry and calls ``client.place_order``. On any failure it
    returns ``None`` so the order falls back to manual fulfillment (never a
    silent/partial order). The buyer address is taken from
    ``draft.shipping_address`` (expected to already match the AliExpress
    logistics_address shape); a real Naver->AliExpress address/SKU mapping must be
    validated against a real paid order before enabling in production.
    """

    async def _place(draft: FulfillmentDraft) -> str | None:
        item: dict = {
            "product_id": str(draft.source_product_id),
            "product_count": int(draft.quantity),
        }
        sku_attr = (draft.shipping_address or {}).pop("sku_attr", None)
        if sku_attr:
            item["sku_attr"] = sku_attr

        result = await client.place_order(
            logistics_address=draft.shipping_address or {},
            product_items=[item],
        )
        if not result.is_success or not result.order_ids:
            logger.warning(
                "ds_place_order_failed",
                naver_order_id=draft.naver_order_id,
                error_code=result.error_code,
                error_msg=result.error_msg,
            )
            return None

        ali_order_id = result.order_ids[0]
        logger.info(
            "ds_order_created_unpaid",
            naver_order_id=draft.naver_order_id,
            ali_order_id=ali_order_id,
        )
        return ali_order_id

    return _place
