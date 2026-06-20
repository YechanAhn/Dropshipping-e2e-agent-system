"""
AliExpress API client package.

Provides the affiliate API client and Pydantic models for interacting
with the AliExpress platform.
"""

from dropagent.config import AliExpressSettings, get_settings

from .affiliate_api import AliExpressAffiliateClient
from .ds_api import AliExpressDSClient
from .models import (
    AliPriceInfo,
    AliProduct,
    AliProductDetail,
    AliProductVariant,
    AliSearchResult,
    AliSellerInfo,
    AliShippingInfo,
)


def get_ali_client(settings: AliExpressSettings | None = None):
    """Return the right AliExpress client for the current credentials.

    Prefers the Dropshipping (DS) client when a DS ``access_token`` is
    configured (KRW prices + ordering); otherwise falls back to the Affiliate
    client. Both share the same ``search_products`` / ``get_product_detail``
    surface, so callers are agnostic.
    """
    settings = settings or get_settings().aliexpress
    if settings.access_token:
        return AliExpressDSClient(settings)
    return AliExpressAffiliateClient(settings)


__all__ = [
    "AliExpressAffiliateClient",
    "AliExpressDSClient",
    "AliPriceInfo",
    "AliProduct",
    "AliProductDetail",
    "AliProductVariant",
    "AliSearchResult",
    "AliSellerInfo",
    "AliShippingInfo",
    "get_ali_client",
]
