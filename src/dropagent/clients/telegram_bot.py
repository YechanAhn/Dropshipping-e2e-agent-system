"""
Telegram notification bot client.

Sends formatted notifications, product recommendations, daily reports,
error alerts, and approval requests to a configured Telegram chat via
the ``python-telegram-bot`` library.
"""

import json
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from dropagent.config import TelegramSettings, get_settings
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# Maximum Telegram message length (UTF-8 chars)
MAX_MESSAGE_LENGTH = 4096


class TelegramNotifier:
    """
    Async Telegram notification client.

    Uses the ``python-telegram-bot`` library (v21+) which provides native
    ``asyncio`` support.  All public methods are fire-and-forget safe --
    they return ``True``/``False`` rather than raising on send failure.
    """

    def __init__(self, settings: TelegramSettings | None = None) -> None:
        """
        Args:
            settings: Telegram bot token and target chat ID.
                      Falls back to ``get_settings().telegram``.
        """
        self._settings = settings or get_settings().telegram
        self._bot = Bot(token=self._settings.bot_token)
        self._chat_id = self._settings.chat_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
        """Truncate text to fit within Telegram's message length limit."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 20] + "\n...(truncated)"

    async def _send(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> bool:
        """
        Low-level send helper.  Returns ``True`` on success, ``False`` on failure.
        """
        # Map string parse mode to telegram constant
        mode_map = {
            "HTML": ParseMode.HTML,
            "MARKDOWN": ParseMode.MARKDOWN,
            "MARKDOWN_V2": ParseMode.MARKDOWN_V2,
        }
        telegram_parse_mode = mode_map.get(parse_mode.upper(), ParseMode.HTML)

        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=self._truncate(text),
                parse_mode=telegram_parse_mode,
                reply_markup=reply_markup,
            )
            return True
        except TelegramError as exc:
            logger.error("telegram_send_error", error=str(exc), chat_id=self._chat_id)
            return False
        except Exception as exc:
            logger.error("telegram_unexpected_error", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a plain text message to the configured chat.

        Args:
            text: Message body (may contain HTML / Markdown formatting).
            parse_mode: Telegram parse mode (``HTML``, ``MARKDOWN``, ``MARKDOWN_V2``).

        Returns:
            ``True`` if the message was sent successfully.
        """
        logger.info("telegram_send_message", length=len(text))
        return await self._send(text, parse_mode=parse_mode)

    async def send_product_recommendation(self, product: dict[str, Any]) -> bool:
        """
        Send a formatted product recommendation card.

        Expected *product* keys:

        - ``title`` -- product name
        - ``price`` -- current sale price
        - ``currency`` -- price currency
        - ``image_url`` -- product image
        - ``product_url`` -- link to product
        - ``margin_rate`` -- estimated margin rate (optional)
        - ``order_count`` -- sales volume (optional)
        - ``rating`` -- star rating (optional)
        - ``category`` -- category name (optional)

        Args:
            product: Dictionary with product data.

        Returns:
            ``True`` if sent successfully.
        """
        title = product.get("title", "Unknown product")
        price = product.get("price", "N/A")
        currency = product.get("currency", "USD")
        url = product.get("product_url", "")
        margin = product.get("margin_rate", "N/A")
        orders = product.get("order_count", "N/A")
        rating = product.get("rating", "N/A")
        category = product.get("category", "N/A")

        message = (
            "<b>New Product Recommendation</b>\n"
            "-----------------------------\n"
            f"<b>{title}</b>\n\n"
            f"Price: {currency} {price}\n"
            f"Category: {category}\n"
            f"Rating: {rating}\n"
            f"Orders: {orders}\n"
            f"Est. Margin: {margin}%\n\n"
            f'<a href="{url}">View Product</a>'
        )

        logger.info("telegram_send_product_recommendation", title=title)
        return await self._send(message, parse_mode="HTML")

    async def send_daily_report(self, stats: dict[str, Any]) -> bool:
        """
        Send a formatted daily operations report.

        Expected *stats* keys:

        - ``date`` -- report date
        - ``products_analyzed`` -- number of products analyzed
        - ``products_registered`` -- number of products registered
        - ``orders_processed`` -- number of orders processed
        - ``total_revenue`` -- total revenue (KRW)
        - ``avg_margin`` -- average margin rate
        - ``errors`` -- number of errors encountered
        - ``top_products`` -- list of top product names (optional)

        Args:
            stats: Dictionary with daily statistics.

        Returns:
            ``True`` if sent successfully.
        """
        date = stats.get("date", "N/A")
        analyzed = stats.get("products_analyzed", 0)
        registered = stats.get("products_registered", 0)
        orders = stats.get("orders_processed", 0)
        revenue = stats.get("total_revenue", 0)
        avg_margin = stats.get("avg_margin", "N/A")
        errors = stats.get("errors", 0)
        top_products = stats.get("top_products", [])

        top_section = ""
        if top_products:
            top_list = "\n".join(f"  - {p}" for p in top_products[:5])
            top_section = f"\n<b>Top Products:</b>\n{top_list}\n"

        message = (
            f"<b>Daily Report - {date}</b>\n"
            "================================\n\n"
            f"Products Analyzed: {analyzed}\n"
            f"Products Registered: {registered}\n"
            f"Orders Processed: {orders}\n"
            f"Total Revenue: {revenue:,} KRW\n"
            f"Avg. Margin: {avg_margin}%\n"
            f"Errors: {errors}\n"
            f"{top_section}"
        )

        logger.info("telegram_send_daily_report", date=date)
        return await self._send(message, parse_mode="HTML")

    async def send_error_alert(self, error: str, context: str) -> bool:
        """
        Send an error alert notification.

        Args:
            error: Error message or exception string.
            context: Description of where/when the error occurred.

        Returns:
            ``True`` if sent successfully.
        """
        message = (
            "<b>ERROR ALERT</b>\n"
            "================================\n\n"
            f"<b>Context:</b> {context}\n\n"
            f"<b>Error:</b>\n<code>{error}</code>"
        )

        logger.info("telegram_send_error_alert", context=context)
        return await self._send(message, parse_mode="HTML")

    async def send_approval_request(
        self,
        product: dict[str, Any],
        callback_id: str,
    ) -> bool:
        """
        Send a product registration approval request with inline keyboard buttons.

        The inline keyboard provides "Approve" and "Reject" buttons whose
        callback data encodes the *callback_id* so that a webhook handler
        can identify which product the user is responding to.

        Args:
            product: Dictionary with product data (same keys as
                     ``send_product_recommendation``).
            callback_id: Unique identifier for this approval request.

        Returns:
            ``True`` if sent successfully.
        """
        title = product.get("title", "Unknown product")
        price = product.get("price", "N/A")
        currency = product.get("currency", "USD")
        margin = product.get("margin_rate", "N/A")
        orders = product.get("order_count", "N/A")
        url = product.get("product_url", "")

        message = (
            "<b>Product Approval Request</b>\n"
            "================================\n\n"
            f"<b>{title}</b>\n\n"
            f"Price: {currency} {price}\n"
            f"Orders: {orders}\n"
            f"Est. Margin: {margin}%\n\n"
            f'<a href="{url}">View Product</a>\n\n'
            "Please approve or reject this product for registration."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Approve",
                        callback_data=json.dumps({"action": "approve", "id": callback_id}),
                    ),
                    InlineKeyboardButton(
                        text="Reject",
                        callback_data=json.dumps({"action": "reject", "id": callback_id}),
                    ),
                ]
            ]
        )

        logger.info("telegram_send_approval_request", callback_id=callback_id, title=title)
        return await self._send(message, parse_mode="HTML", reply_markup=keyboard)
