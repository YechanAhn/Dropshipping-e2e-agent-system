"""
Unit tests for the AliExpress Dropshipping (DS) API client.

Uses canned responses shaped like the REAL live API (captured 2026-06-20) via a
fake httpx client -- no network, no credentials. Verifies the IOP signing,
KRW-native parsing, and the get_ali_client factory.
"""
import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace

from dropagent.clients.aliexpress.ds_api import AliExpressDSClient

# ─── Fake settings + HTTP ────────────────────────────────────────────────


def _settings(access_token: str = "tok-123", refresh_token: str = "rt-1") -> SimpleNamespace:
    return SimpleNamespace(
        app_key="537474",
        app_secret="SECRET",
        access_token=access_token,
        refresh_token=refresh_token,
        target_currency="KRW",
        target_language="KO",
        search_locale="ko_KR",
        ship_to_country="KR",
    )


_SEARCH_RESPONSE = {
    "aliexpress_ds_text_search_response": {
        "code": "00",
        "data": {
            "pageIndex": 1,
            "pageSize": 2,
            "totalCount": 43182,
            "products": {
                "selection_search_product": [
                    {
                        "itemId": "1005008089329682",
                        "title": "E6S 무선 블루투스 이어폰 TWS 헤드셋",
                        "targetSalePrice": "3980",
                        "targetOriginalPrice": "4183",
                        "targetOriginalPriceCurrency": "KRW",
                        "itemMainPic": "https://ae-pic-a1.example/main.jpg",
                        "score": "4.5",
                        "orders": "5,000+",
                        "cateId": "44,100000306,63705",
                        "itemUrl": "//www.aliexpress.com/item/1005008089329682.html",
                        "salePriceCurrency": "CNY",
                    }
                ]
            },
        },
    }
}

_DETAIL_RESPONSE = {
    "aliexpress_ds_product_get_response": {
        "rsp_code": 200,
        "result": {
            "ae_item_base_info_dto": {
                "product_id": "1005008089329682",
                "subject": "E6S TWS 블루투스 이어폰 무선 헤드셋",
                "mobile_detail": json.dumps(
                    {"moduleList": [{"type": "text", "data": {"content": "제품 설명 텍스트입니다"}}]}
                ),
                "avg_evaluation_rating": "4.5",
                "sales_count": "5000",
                "category_id": "63705",
            },
            "ae_multimedia_info_dto": {
                "image_urls": "https://ae01.example/1.jpg;https://ae01.example/2.jpg",
                "ae_video_dtos": {"ae_video_d_t_o": [{"media_url": "https://v.example/1.mp4"}]},
            },
            "logistics_info_dto": {"delivery_time": 7, "ship_to_country": "KR"},
            "ae_item_sku_info_dtos": {
                "ae_item_sku_info_d_t_o": [
                    {
                        "sku_id": "12000043996448083",
                        "offer_sale_price": "5040",
                        "sku_price": "10957",
                        "currency_code": "KRW",
                        "sku_available_stock": 37,
                        "ae_sku_property_dtos": {
                            "ae_sku_property_d_t_o": [
                                {
                                    "sku_property_name": "색상",
                                    "sku_property_value": "검정색",
                                    "sku_image": "https://ae01.example/c.jpg",
                                }
                            ]
                        },
                    },
                    {
                        "sku_id": "12000043996448084",
                        "offer_sale_price": "5990",
                        "sku_price": "11900",
                        "currency_code": "KRW",
                        "sku_available_stock": 10,
                    },
                ]
            },
            "ae_store_info": {"store_id": "900", "store_name": "My Store"},
        },
    }
}


class _FakeResp:
    status_code = 200
    text = ""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeHttp:
    """Routes by the ``method`` form field to the matching canned response."""

    def __init__(self) -> None:
        self.is_closed = False
        self.last_data: dict | None = None

    async def post(self, url, data=None, headers=None):  # noqa: ANN001
        self.last_data = data
        method = data.get("method")
        if method == "aliexpress.ds.text.search":
            return _FakeResp(_SEARCH_RESPONSE)
        if method == "aliexpress.ds.product.get":
            return _FakeResp(_DETAIL_RESPONSE)
        return _FakeResp({"error_response": {"code": "unknown", "msg": "no route"}})

    async def get(self, url, params=None):  # noqa: ANN001
        self.last_params = params
        return _FakeResp(
            {"access_token": "new-access-token", "refresh_token": "new-refresh", "expire_time": 9999}
        )

    async def aclose(self) -> None:
        self.is_closed = True


def _client(http=None, access_token="tok-123") -> AliExpressDSClient:
    return AliExpressDSClient(settings=_settings(access_token), http_client=http or _FakeHttp())


# ─── Signing ─────────────────────────────────────────────────────────────


def test_sign_is_iop_style_no_method_prefix_includes_token():
    c = _client()
    params = {"app_key": "537474", "access_token": "tok-123", "method": "aliexpress.ds.product.get"}
    expected_base = "access_tokentok-123app_key537474methodaliexpress.ds.product.get"
    expected = hmac.new(b"SECRET", expected_base.encode(), hashlib.sha256).hexdigest().upper()
    assert c._sign(params) == expected
    # Must NOT be the TOP style (method name prefixed) which DS rejects.
    top_base = "aliexpress.ds.product.get" + expected_base
    top_sign = hmac.new(b"SECRET", top_base.encode(), hashlib.sha256).hexdigest().upper()
    assert c._sign(params) != top_sign


# ─── search_products ─────────────────────────────────────────────────────


async def test_search_products_parses_krw_and_korean_title():
    c = _client()
    result = await c.search_products("wireless earbuds", page_size=2)

    assert result.total_count == 43182
    assert len(result.products) == 1
    p = result.products[0]
    assert p.product_id == "1005008089329682"
    assert "무선 블루투스" in p.title
    assert p.price.sale_price == Decimal("3980")  # targetSalePrice, already KRW
    assert p.currency == "KRW"
    assert p.order_count == 5000  # "5,000+" -> 5000
    assert p.image_url == "https://ae-pic-a1.example/main.jpg"
    assert p.product_url.startswith("https://")


async def test_search_sends_token_and_krw_params():
    http = _FakeHttp()
    c = _client(http)
    await c.search_products("이어폰")
    assert http.last_data["access_token"] == "tok-123"
    assert http.last_data["currency"] == "KRW"
    assert http.last_data["countryCode"] == "KR"
    assert http.last_data["method"] == "aliexpress.ds.text.search"
    assert "sign" in http.last_data


# ─── get_product_detail ──────────────────────────────────────────────────


async def test_get_product_detail_parses_cheapest_sku_krw():
    c = _client()
    details = await c.get_product_detail(["1005008089329682"])
    assert len(details) == 1
    d = details[0]
    assert d.title == "E6S TWS 블루투스 이어폰 무선 헤드셋"
    # cheapest SKU offer_sale_price (5040 < 5990), already KRW
    assert d.price.sale_price == Decimal("5040")
    assert d.currency == "KRW"
    assert d.image_url == "https://ae01.example/1.jpg"
    assert d.shipping_info.days == 7
    assert "제품 설명" in d.description
    assert len(d.options) == 2
    assert d.options[0].value == "검정색"


async def test_get_product_detail_parses_gallery_and_video():
    c = _client()
    d = (await c.get_product_detail(["1005008089329682"]))[0]
    assert d.image_urls == ["https://ae01.example/1.jpg", "https://ae01.example/2.jpg"]
    assert d.video_url == "https://v.example/1.mp4"


async def test_get_product_detail_empty_input():
    c = _client()
    assert await c.get_product_detail([]) == []


# ─── token refresh ───────────────────────────────────────────────────────


async def test_refresh_access_token_updates_in_memory_token():
    http = _FakeHttp()
    c = _client(http)
    data = await c.refresh_access_token()
    assert data["access_token"] == "new-access-token"
    assert c._access_token == "new-access-token"
    # signs with IOP /rest path-prefixed base (sign present in the request).
    assert http.last_params is not None and "sign" in http.last_params
    assert http.last_params["refresh_token"] == "rt-1"


# ─── factory ─────────────────────────────────────────────────────────────


def test_get_ali_client_prefers_ds_when_token_present():
    from dropagent.clients.aliexpress import (
        AliExpressAffiliateClient,
        AliExpressDSClient,
        get_ali_client,
    )

    ds = get_ali_client(_settings(access_token="tok"))
    assert isinstance(ds, AliExpressDSClient)
    aff = get_ali_client(_settings(access_token=""))
    assert isinstance(aff, AliExpressAffiliateClient)


# ─── robustness fixes (from code review) ─────────────────────────────────


class _StaticHttp:
    """Returns fixed payloads for post()/get()."""

    def __init__(self, post_payload=None, get_payload=None) -> None:  # noqa: ANN001
        self.is_closed = False
        self._post = post_payload
        self._get = get_payload

    async def post(self, url, data=None, headers=None):  # noqa: ANN001
        return _FakeResp(self._post)

    async def get(self, url, params=None):  # noqa: ANN001
        return _FakeResp(self._get)

    async def aclose(self) -> None:
        self.is_closed = True


def _detail_payload(sku: dict, base: dict | None = None, logistics: dict | None = None) -> dict:
    return {
        "aliexpress_ds_product_get_response": {
            "rsp_code": 200,
            "result": {
                "ae_item_base_info_dto": base or {"subject": "X", "target_sale_price": "9999"},
                "ae_item_sku_info_dtos": {"ae_item_sku_info_d_t_o": [sku]},
                "logistics_info_dto": logistics or {"delivery_time": 7},
            },
        }
    }


async def test_detail_zero_priced_sku_falls_back_to_base_not_zero():
    # offer_sale_price="0" is truthy as a string -> must NOT yield sale_price 0.
    payload = _detail_payload({"sku_id": "1", "offer_sale_price": "0", "sku_price": "0", "currency_code": "KRW"})
    c = AliExpressDSClient(settings=_settings(), http_client=_StaticHttp(post_payload=payload))
    d = (await c.get_product_detail(["1"]))[0]
    assert d.price.sale_price == Decimal("9999")  # base fallback, not 0


async def test_detail_comma_stock_does_not_crash():
    payload = _detail_payload(
        {"sku_id": "1", "offer_sale_price": "5040", "currency_code": "KRW", "sku_available_stock": "1,200"}
    )
    c = AliExpressDSClient(settings=_settings(), http_client=_StaticHttp(post_payload=payload))
    d = (await c.get_product_detail(["1"]))[0]
    assert d.price.sale_price == Decimal("5040")
    assert d.options[0].stock == 1200


async def test_detail_range_delivery_time_takes_first_int():
    payload = _detail_payload(
        {"sku_id": "1", "offer_sale_price": "5040", "currency_code": "KRW"},
        logistics={"delivery_time": "7-15"},
    )
    c = AliExpressDSClient(settings=_settings(), http_client=_StaticHttp(post_payload=payload))
    d = (await c.get_product_detail(["1"]))[0]
    assert d.shipping_info.days == 7  # NOT 715


async def test_detail_skips_on_no_result():
    payload = {"aliexpress_ds_product_get_response": {"rsp_code": 605, "rsp_msg": "ITEM_ID_NOT_FOUND"}}
    c = AliExpressDSClient(settings=_settings(), http_client=_StaticHttp(post_payload=payload))
    assert await c.get_product_detail(["bad"]) == []


async def test_refresh_raises_on_error_envelope():
    import pytest

    from dropagent.utils.exceptions import APIError

    http = _StaticHttp(get_payload={"code": "InvalidTokenError", "message": "refresh token expired"})
    c = AliExpressDSClient(settings=_settings(), http_client=http)
    with pytest.raises(APIError) as ei:
        await c.refresh_access_token()
    assert "InvalidTokenError" in str(ei.value)
    # the access_token must NOT be overwritten on failure
    assert c._access_token == "tok-123"


async def test_search_handles_single_dict_and_empty():
    single = {
        "aliexpress_ds_text_search_response": {
            "data": {
                "totalCount": 1,
                "products": {
                    "selection_search_product": {
                        "itemId": "9",
                        "title": "T",
                        "targetSalePrice": "1000",
                        "targetOriginalPriceCurrency": "KRW",
                    }
                },
            }
        }
    }
    c = AliExpressDSClient(settings=_settings(), http_client=_StaticHttp(post_payload=single))
    r = await c.search_products("x")
    assert len(r.products) == 1 and r.products[0].product_id == "9"

    empty = {"aliexpress_ds_text_search_response": {"data": {"totalCount": 0, "products": {}}}}
    c2 = AliExpressDSClient(settings=_settings(), http_client=_StaticHttp(post_payload=empty))
    r2 = await c2.search_products("x")
    assert r2.products == [] and r2.total_count == 0
