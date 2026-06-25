"""
AliExpress Dropshipping (DS) API client.

Implements the ``aliexpress.ds.*`` family on the GOP gateway
(https://api-sg.aliexpress.com/sync). Unlike the Affiliate API, DS business
calls are authenticated with a user ``access_token`` and use **IOP-style
signing** (sorted key+value concatenation WITHOUT the method-name prefix, with
the access_token included in the signed base). This was verified live; the
TOP-style signing used by the affiliate client yields ``IncompleteSignature``
on DS authenticated calls.

Prices are requested in KRW (``target_currency``) so they come back already in
won -- no FX guessing. Exposes the same surface the pipeline expects from the
affiliate client (``search_products`` / ``get_product_detail`` returning the
shared ``AliProduct`` / ``AliProductDetail`` models) so it is a drop-in.

Reference: AliExpress Open Platform, Drop Shipping API.
"""

import asyncio
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from dropagent.config import AliExpressSettings, get_settings
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

from .models import (
    AliPriceInfo,
    AliProduct,
    AliProductDetail,
    AliProductVariant,
    AliSearchResult,
    AliSellerInfo,
    AliShippingInfo,
)

logger = get_logger(__name__)

GATEWAY_URL = "https://api-sg.aliexpress.com/sync"
TOKEN_REFRESH_URL = "https://api-sg.aliexpress.com/rest/auth/token/refresh"

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
BACKOFF_MULTIPLIER = 2.0


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    """Best-effort Decimal parse (handles None, '', commas)."""
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value).replace(",", "").strip() or default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    """Parse a count from messy strings like '5,000+' -> 5000 (strips separators)."""
    if value is None:
        return default
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else default


def _first_int(value: Any, default: int = 0) -> int:
    """First integer token of a value -- for ranges like '7-15' -> 7 (delivery time).

    Unlike :func:`_to_int` it does NOT concatenate all digits ('7-15' would
    wrongly become 715), so use this for range-formatted fields.
    """
    if value is None:
        return default
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else default


@dataclass
class FreightOption:
    """A shipping option from ds.freight.query (cost already in target currency)."""

    code: str
    company: str
    fee: Decimal
    free_shipping: bool = False
    min_days: int = 0
    max_days: int = 0
    currency: str = "KRW"


@dataclass
class PlaceOrderResult:
    """Result of trade.buy.placeorder. ``is_success`` + the created order ids.

    NOTE: placing an order creates a real (unpaid) order obligation on AliExpress.
    Payment is a SEPARATE manual step and is never performed by this client.
    """

    is_success: bool
    order_ids: list[str] = field(default_factory=list)
    error_code: str = ""
    error_msg: str = ""


class AliExpressDSClient:
    """
    Async client for the AliExpress Dropshipping API (token-authenticated).

    Args:
        settings: AliExpress settings (key/secret/access_token). Falls back to
            ``get_settings().aliexpress``.
        http_client: Optional pre-configured httpx.AsyncClient (for tests).
    """

    def __init__(
        self,
        settings: AliExpressSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings().aliexpress
        self._client = http_client or httpx.AsyncClient(timeout=40.0)
        self._owns_client = http_client is None
        self._access_token = self._settings.access_token

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "AliExpressDSClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Signing (IOP style: sorted key+value, NO api-name prefix)
    # ------------------------------------------------------------------

    def _sign(self, params: dict[str, str]) -> str:
        base = "".join(f"{k}{params[k]}" for k in sorted(params))
        return hmac.new(
            self._settings.app_secret.encode("utf-8"),
            base.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

    def _common_params(self, api_name: str) -> dict[str, str]:
        params = {
            "app_key": self._settings.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "method": api_name,
            "v": "2.0",
            "format": "json",
        }
        if self._access_token:
            params["access_token"] = self._access_token
        return params

    # ------------------------------------------------------------------
    # HTTP with retry
    # ------------------------------------------------------------------

    async def _request(self, api_name: str, business_params: dict[str, Any]) -> dict[str, Any]:
        params = self._common_params(api_name)
        for key, value in business_params.items():
            if value is not None:
                params[key] = str(value)
        params["sign"] = self._sign(params)

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.post(
                    GATEWAY_URL,
                    data=params,
                    headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError(
                        message="AliExpress DS API rate limit exceeded",
                        api_name="aliexpress_ds",
                        retry_after=retry_after,
                    )
                if response.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                    continue
                if response.status_code != 200:
                    raise APIError(
                        message=f"AliExpress DS API error: HTTP {response.status_code}",
                        api_name="aliexpress_ds",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                data = response.json()
                if "error_response" in data:
                    err = data["error_response"]
                    code = str(err.get("code", ""))
                    msg = str(err.get("msg", ""))
                    # Make an expired/invalid access_token visibly attributable
                    # (else a swallowed per-product failure looks like "no data").
                    # The refresh_token rotation is handled out-of-band by
                    # scripts/refresh_ali_token.py (cron); flag it loudly here.
                    if "token" in (code + msg).lower():
                        logger.warning(
                            "aliexpress_ds_token_error",
                            code=code,
                            msg=msg,
                            hint="run scripts/refresh_ali_token.py to rotate the token",
                        )
                    raise APIError(
                        message=f"AliExpress DS API error [{code}]: {msg}",
                        api_name="aliexpress_ds",
                        response_body=str(err),
                    )
                return data
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(INITIAL_BACKOFF * (BACKOFF_MULTIPLIER ** attempt))
                    continue
                raise APIError(
                    message=f"AliExpress DS API network error after {MAX_RETRIES} retries: {exc}",
                    api_name="aliexpress_ds",
                    original_error=exc,
                ) from exc

        raise APIError(
            message=f"AliExpress DS API failed after {MAX_RETRIES} retries",
            api_name="aliexpress_ds",
            original_error=last_error,
        )

    # ------------------------------------------------------------------
    # Token refresh (IOP /rest signing: path-prefixed base)
    # ------------------------------------------------------------------

    async def refresh_access_token(self) -> dict[str, Any]:
        """Refresh the DS access_token using the stored refresh_token.

        Calls ``/rest/auth/token/refresh`` (IOP signing = ``path`` + sorted
        key+value). Updates the in-memory access_token and returns the raw token
        payload (access_token, refresh_token, expire_time, ...). Callers should
        persist the returned tokens (see scripts/refresh_ali_token.py).
        """
        if not self._settings.refresh_token:
            raise APIError(message="No refresh_token configured", api_name="aliexpress_ds")

        path = "/auth/token/refresh"
        params = {
            "app_key": self._settings.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "refresh_token": self._settings.refresh_token,
        }
        base = path + "".join(f"{k}{params[k]}" for k in sorted(params))
        params["sign"] = hmac.new(
            self._settings.app_secret.encode("utf-8"),
            base.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        response = await self._client.get(TOKEN_REFRESH_URL, params=params)
        if response.status_code != 200:
            raise APIError(
                message=f"AliExpress DS token refresh failed: HTTP {response.status_code}",
                api_name="aliexpress_ds",
                status_code=response.status_code,
                response_body=response.text,
            )
        data = response.json()
        # The IOP /rest gateway returns HTTP 200 with an error envelope on
        # failure (e.g. expired/invalid refresh_token): {code, message, type}.
        # Surface the gateway's code+message; keep the raw body out of the
        # user-facing message (it may carry diagnostic fields).
        token = data.get("access_token")
        if not token:
            code = str(data.get("code", "")) or "unknown"
            message = str(data.get("message") or data.get("msg") or "no access_token returned")
            raise APIError(
                message=f"AliExpress DS token refresh failed [{code}]: {message}",
                api_name="aliexpress_ds",
                response_body=str(data),
            )
        self._access_token = token
        logger.info("aliexpress_ds_token_refreshed", expire_time=data.get("expire_time"))
        return data

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_search_item(self, raw: dict[str, Any]) -> AliProduct:
        currency = raw.get("targetOriginalPriceCurrency") or self._settings.target_currency
        item_url = str(raw.get("itemUrl", ""))
        if item_url.startswith("//"):
            item_url = "https:" + item_url
        return AliProduct(
            product_id=str(raw.get("itemId", "")),
            title=raw.get("title", ""),
            price=AliPriceInfo(
                original_price=_to_decimal(raw.get("targetOriginalPrice", raw.get("targetSalePrice"))),
                sale_price=_to_decimal(raw.get("targetSalePrice")),
            ),
            currency=currency,
            category_id=str(raw.get("cateId", "")).split(",")[0] or None,
            image_url=raw.get("itemMainPic", ""),
            product_url=item_url,
            rating=_to_decimal(raw.get("score"), "0"),
            order_count=_to_int(raw.get("orders")),
        )

    @staticmethod
    def _extract_description(base_info: dict[str, Any]) -> str:
        """Pull readable text from ae_item_base_info_dto (detail or mobile_detail)."""
        detail = base_info.get("detail")
        if detail:
            return str(detail)
        mobile = base_info.get("mobile_detail")
        if not mobile:
            return ""
        try:
            modules = json.loads(mobile).get("moduleList", [])
        except (ValueError, TypeError):
            return ""
        # Many AliExpress detail pages put copy in text OR html modules (some are
        # image-only). Pull text from both so the 상세페이지 generator gets source
        # copy for more products.
        texts = []
        for m in modules:
            content = (m.get("data", {}) or {}).get("content", "")
            if m.get("type") in ("text", "html") and content:
                texts.append(str(content))
        return "\n".join(texts)

    def _parse_detail(self, product_id: str, result: dict[str, Any]) -> AliProductDetail:
        base = result.get("ae_item_base_info_dto", {}) or {}
        multimedia = result.get("ae_multimedia_info_dto", {}) or {}
        logistics = result.get("logistics_info_dto", {}) or {}
        sku_wrap = result.get("ae_item_sku_info_dtos", {}) or {}
        skus = sku_wrap.get("ae_item_sku_info_d_t_o", []) or []
        if isinstance(skus, dict):
            skus = [skus]

        # Price: cheapest *positive* SKU offer price (already KRW via
        # target_currency). Filter on the PARSED value: a SKU can carry
        # offer_sale_price="0" (out-of-stock/placeholder), which is truthy as a
        # string -- keeping it would make min() return 0 and defeat the margin
        # floor downstream.
        sku_prices = [d for s in skus if (d := _to_decimal(s.get("offer_sale_price"))) > 0]
        sale_price = min(sku_prices) if sku_prices else _to_decimal(base.get("target_sale_price"))
        orig_prices = [d for s in skus if (d := _to_decimal(s.get("sku_price"))) > 0]
        original_price = min(orig_prices) if orig_prices else sale_price
        currency = next(
            (s.get("currency_code") for s in skus if s.get("currency_code")),
            self._settings.target_currency,
        )

        images = [u for u in str(multimedia.get("image_urls", "")).split(";") if u]
        videos = (multimedia.get("ae_video_dtos", {}) or {}).get("ae_video_d_t_o", []) or []
        if isinstance(videos, dict):
            videos = [videos]
        video_url = next((v.get("media_url") for v in videos if v.get("media_url")), None)

        variants: list[AliProductVariant] = []
        for s in skus:
            props = (s.get("ae_sku_property_dtos", {}) or {}).get("ae_sku_property_d_t_o", []) or []
            if isinstance(props, dict):
                props = [props]
            name = ", ".join(p.get("sku_property_name", "") for p in props)
            value = ", ".join(p.get("sku_property_value", "") for p in props)
            variants.append(
                AliProductVariant(
                    sku_id=str(s.get("sku_id", "")),
                    name=name,
                    value=value,
                    image_url=next((p.get("sku_image") for p in props if p.get("sku_image")), None),
                    price=_to_decimal(s.get("offer_sale_price")) if s.get("offer_sale_price") else None,
                    # _to_int tolerates separators ('1,200'); raw int() would crash the batch.
                    stock=_to_int(s["sku_available_stock"]) if s.get("sku_available_stock") is not None else None,
                )
            )

        return AliProductDetail(
            product_id=str(base.get("product_id", product_id)),
            title=base.get("subject", ""),
            price=AliPriceInfo(original_price=original_price, sale_price=sale_price),
            currency=currency,
            category_id=str(base.get("category_id", "")) or None,
            image_url=images[0] if images else "",
            image_urls=images,
            video_url=video_url,
            product_url=base.get("detail_url", ""),
            rating=_to_decimal(base.get("avg_evaluation_rating"), "0"),
            order_count=_to_int(base.get("sales_count")),
            shipping_info=AliShippingInfo(
                # delivery_time is often a range like '7-15' -> take the first int.
                days=_first_int(logistics.get("delivery_time")),
                cost=Decimal("0.00"),
            ),
            seller_info=AliSellerInfo(
                id=str((result.get("ae_store_info", {}) or {}).get("store_id", "")),
                name=(result.get("ae_store_info", {}) or {}).get("store_name", ""),
            ),
            description=self._extract_description(base),
            options=variants,
            reviews_count=_to_int(base.get("evaluation_count")),
        )

    # ------------------------------------------------------------------
    # Public API (drop-in compatible with the affiliate client)
    # ------------------------------------------------------------------

    async def search_products(
        self,
        keywords: str,
        category_id: str | None = None,
        min_price: float | None = None,  # noqa: ARG002 - accepted for interface parity
        max_price: float | None = None,  # noqa: ARG002
        page: int = 1,
        page_size: int = 50,
    ) -> AliSearchResult:
        """Search AliExpress products in KRW via ``aliexpress.ds.text.search``."""
        logger.info("aliexpress_ds_search", keywords=keywords, page=page, page_size=page_size)
        biz: dict[str, Any] = {
            "keyWord": keywords,
            "local": self._settings.search_locale,
            "countryCode": self._settings.ship_to_country,
            "currency": self._settings.target_currency,
            "pageSize": min(page_size, 50),
            "pageIndex": page,
            "sortBy": "orders,desc",
        }
        if category_id is not None:
            biz["categoryId"] = category_id

        data = await self._request("aliexpress.ds.text.search", biz)
        result = data.get("aliexpress_ds_text_search_response", {}).get("data", {})
        raw_products = (result.get("products", {}) or {}).get("selection_search_product", []) or []
        if isinstance(raw_products, dict):
            raw_products = [raw_products]

        return AliSearchResult(
            products=[self._parse_search_item(p) for p in raw_products],
            total_count=_to_int(result.get("totalCount")),
            current_page=_to_int(result.get("pageIndex"), page),
        )

    async def get_hot_products(self, category_id: str, page: int = 1) -> AliSearchResult:
        """Interface parity with the affiliate client.

        The DS API has no affiliate-style "hot products by category" endpoint and
        this system is demand-first (it sources from Naver discovery, not from an
        AliExpress hot-list), so this returns an empty result instead of crashing
        the caller. Logged so the no-op is visible (not silent).
        """
        logger.info("aliexpress_ds_hot_products_unsupported", category_id=category_id)
        return AliSearchResult(products=[], total_count=0, current_page=page)

    async def get_product_detail(self, product_ids: list[str]) -> list[AliProductDetail]:
        """Fetch detail (KRW price, images, video, options) via ``aliexpress.ds.product.get``."""
        if not product_ids:
            return []
        logger.info("aliexpress_ds_product_detail", product_count=len(product_ids))

        details: list[AliProductDetail] = []
        for pid in product_ids[:20]:
            biz = {
                "product_id": pid,
                "ship_to_country": self._settings.ship_to_country,
                "target_currency": self._settings.target_currency,
                "target_language": self._settings.target_language.lower()[:2],
            }
            try:
                data = await self._request("aliexpress.ds.product.get", biz)
            except APIError as exc:
                logger.warning("aliexpress_ds_detail_failed", product_id=pid, error=str(exc))
                continue
            resp = data.get("aliexpress_ds_product_get_response", {})
            result = resp.get("result")
            if not result:
                # No result -> surface the gateway's rsp_msg (e.g. ITEM_ID_NOT_FOUND)
                # so the skip is attributable, not a silent empty.
                logger.warning(
                    "aliexpress_ds_detail_no_result",
                    product_id=pid,
                    rsp_code=resp.get("rsp_code"),
                    rsp_msg=resp.get("rsp_msg"),
                )
                continue
            details.append(self._parse_detail(pid, result))
        return details

    async def query_freight(
        self,
        product_id: str,
        sku_id: str,
        *,
        quantity: int = 1,
        country: str | None = None,
    ) -> list[FreightOption]:
        """Live shipping options/cost for a SKU via ``aliexpress.ds.freight.query``.

        Non-mutating. Returns the available delivery options (fee already in
        ``target_currency``), cheapest-first. Used to put a REAL shipping cost into
        the landed-cost estimate instead of assuming 0.
        """
        req = {
            "productId": str(product_id),
            "quantity": quantity,
            "shipToCountry": country or self._settings.ship_to_country,
            "selectedSkuId": str(sku_id),
            "currency": self._settings.target_currency,
            "locale": self._settings.search_locale,
            "language": self._settings.target_language.lower()[:2],
        }
        data = await self._request("aliexpress.ds.freight.query", {"queryDeliveryReq": json.dumps(req)})
        result = data.get("aliexpress_ds_freight_query_response", {}).get("result", {}) or {}
        raw = (result.get("delivery_options", {}) or {}).get("delivery_option_d_t_o", []) or []
        if isinstance(raw, dict):
            raw = [raw]
        options = [
            FreightOption(
                code=str(o.get("code", "")),
                company=str(o.get("company", "")),
                fee=_to_decimal(o.get("shipping_fee_cent")),
                free_shipping=bool(o.get("free_shipping")),
                min_days=_to_int(o.get("min_delivery_days")),
                max_days=_to_int(o.get("max_delivery_days")),
                currency=str(o.get("shipping_fee_currency") or self._settings.target_currency),
            )
            for o in raw
        ]
        options.sort(key=lambda o: o.fee)
        return options

    async def place_order(
        self,
        logistics_address: dict[str, Any],
        product_items: list[dict[str, Any]],
    ) -> PlaceOrderResult:
        """Create an AliExpress order via ``aliexpress.trade.buy.placeorder``.

        ⚠️ This creates a REAL (unpaid) order obligation on AliExpress. It does
        NOT pay -- payment is a separate, human-gated step. Callers must gate this
        behind explicit opt-in (see make_ds_source_order_placer + ALI_AUTO_ORDER).

        Args:
            logistics_address: buyer address dict (country, province, city, address,
                zip, contact_person, mobile_no, full_name, phone_country, locale).
            product_items: list of {product_id, sku_attr|sku_id, product_count,
                logistics_service_name?, order_memo?}.

        Returns:
            PlaceOrderResult with success flag + created order id(s).
        """
        req = {"logistics_address": logistics_address, "product_items": product_items}
        data = await self._request(
            "aliexpress.trade.buy.placeorder", {"param_place_order_request4": json.dumps(req)}
        )
        resp = data.get("aliexpress_trade_buy_placeorder_response", data)
        result = resp.get("result", resp) or {}
        is_success = bool(result.get("is_success") or result.get("isSuccess"))
        order_wrap = result.get("order_list", result.get("orderList", {})) or {}
        if isinstance(order_wrap, dict):
            order_ids = order_wrap.get("number", order_wrap.get("string", []))
        else:
            order_ids = order_wrap
        if isinstance(order_ids, (str, int)):
            order_ids = [order_ids]
        return PlaceOrderResult(
            is_success=is_success,
            order_ids=[str(o) for o in (order_ids or [])],
            error_code=str(result.get("error_code", "")),
            error_msg=str(result.get("error_msg", result.get("errorMsg", ""))),
        )
