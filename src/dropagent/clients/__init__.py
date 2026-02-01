"""
External API client package.

Re-exports the primary client classes for AliExpress, Naver (Shopping,
Commerce, DataLab), exchange rates, and Telegram notifications.
"""

from .aliexpress import AliExpressAffiliateClient
from .exchange_rate import ExchangeRateClient
from .naver import NaverCommerceClient, NaverDataLabClient, NaverShoppingClient
from .telegram_bot import TelegramNotifier

__all__ = [
    "AliExpressAffiliateClient",
    "ExchangeRateClient",
    "NaverCommerceClient",
    "NaverDataLabClient",
    "NaverShoppingClient",
    "TelegramNotifier",
]
