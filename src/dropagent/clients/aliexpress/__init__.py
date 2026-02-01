"""
AliExpress API client package.

Provides the affiliate API client and Pydantic models for interacting
with the AliExpress platform.
"""

from .affiliate_api import AliExpressAffiliateClient
from .models import (
    AliPriceInfo,
    AliProduct,
    AliProductDetail,
    AliProductVariant,
    AliSearchResult,
    AliSellerInfo,
    AliShippingInfo,
)

__all__ = [
    "AliExpressAffiliateClient",
    "AliPriceInfo",
    "AliProduct",
    "AliProductDetail",
    "AliProductVariant",
    "AliSearchResult",
    "AliSellerInfo",
    "AliShippingInfo",
]
