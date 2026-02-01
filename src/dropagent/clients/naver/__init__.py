"""
Naver API client package.

Provides clients for the Naver Shopping Search API, the Naver Commerce
(SmartStore) API, the Naver DataLab Shopping Insight API, and the
underlying authentication helpers.
"""

from .auth import NaverAuth, NaverCommerceAuth
from .commerce_api import NaverCommerceClient
from .datalab_api import NaverDataLabClient
from .models import (
    NaverCommerceProduct,
    NaverOriginProduct,
    NaverShoppingItem,
    NaverShoppingResult,
    NaverTrendGroup,
    NaverTrendItem,
    NaverTrendResult,
)
from .shopping_api import NaverShoppingClient

__all__ = [
    # Auth
    "NaverAuth",
    "NaverCommerceAuth",
    # Clients
    "NaverCommerceClient",
    "NaverDataLabClient",
    "NaverShoppingClient",
    # Models
    "NaverCommerceProduct",
    "NaverOriginProduct",
    "NaverShoppingItem",
    "NaverShoppingResult",
    "NaverTrendGroup",
    "NaverTrendItem",
    "NaverTrendResult",
]
