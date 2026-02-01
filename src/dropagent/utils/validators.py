"""
Validation and sanitization helpers for DropAgent.

Provides lightweight validators for product IDs, prices, categories,
URLs, and an HTML sanitiser used before persisting user-facing text.
"""

import html
import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# AliExpress product-ID validation
# ---------------------------------------------------------------------------

# AliExpress product IDs are purely numeric strings, typically 9-15 digits.
_ALI_PRODUCT_ID_RE = re.compile(r"^\d{9,15}$")


def validate_ali_product_id(product_id: str) -> bool:
    """Return *True* if *product_id* looks like a valid AliExpress product ID.

    AliExpress product IDs consist of 9-15 decimal digits.

    Args:
        product_id: The candidate product ID string.

    Returns:
        ``True`` when valid, ``False`` otherwise.

    Examples:
        >>> validate_ali_product_id("1005006714537300")
        True
        >>> validate_ali_product_id("abc123")
        False
    """
    if not isinstance(product_id, str):
        return False
    return bool(_ALI_PRODUCT_ID_RE.match(product_id))


# ---------------------------------------------------------------------------
# Naver product-ID validation
# ---------------------------------------------------------------------------

# Naver Smart Store product IDs are numeric strings, typically 8-15 digits.
_NAVER_PRODUCT_ID_RE = re.compile(r"^\d{8,15}$")


def validate_naver_product_id(product_id: str) -> bool:
    """Return *True* if *product_id* looks like a valid Naver product ID.

    Naver Commerce product IDs consist of 8-15 decimal digits.

    Args:
        product_id: The candidate product ID string.

    Returns:
        ``True`` when valid, ``False`` otherwise.

    Examples:
        >>> validate_naver_product_id("12345678")
        True
        >>> validate_naver_product_id("short")
        False
    """
    if not isinstance(product_id, str):
        return False
    return bool(_NAVER_PRODUCT_ID_RE.match(product_id))


# ---------------------------------------------------------------------------
# Price validation
# ---------------------------------------------------------------------------

def validate_price(price: float) -> bool:
    """Return *True* if *price* is a positive, finite number.

    Args:
        price: The candidate price value.

    Returns:
        ``True`` when the price is a positive finite number, ``False`` otherwise.

    Examples:
        >>> validate_price(29.99)
        True
        >>> validate_price(-5.0)
        False
        >>> validate_price(0)
        False
    """
    try:
        price_float = float(price)
    except (TypeError, ValueError):
        return False

    if price_float != price_float:  # NaN check
        return False

    if price_float == float("inf") or price_float == float("-inf"):
        return False

    return price_float > 0


# ---------------------------------------------------------------------------
# Category validation
# ---------------------------------------------------------------------------

# Categories are expected to be non-empty strings with 1-200 characters,
# consisting of printable characters (letters, digits, spaces, slashes,
# hyphens, parentheses, and Korean/CJK characters).
_CATEGORY_RE = re.compile(
    r"^[\w\s/\-()&\u3131-\u3163\uac00-\ud7a3\u4e00-\u9fff.,']{1,200}$",
    re.UNICODE,
)


def validate_category(category: str) -> bool:
    """Return *True* if *category* is a valid category name.

    A valid category is a non-empty string of up to 200 characters
    containing letters, digits, spaces, slashes, hyphens, parentheses,
    and Korean / CJK characters.

    Args:
        category: The candidate category string.

    Returns:
        ``True`` when valid, ``False`` otherwise.

    Examples:
        >>> validate_category("Electronics > Phones")
        True
        >>> validate_category("")
        False
    """
    if not isinstance(category, str):
        return False
    return bool(_CATEGORY_RE.match(category.strip()))


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_url(url: str) -> bool:
    """Return *True* if *url* is a syntactically valid HTTP(S) URL.

    Args:
        url: The candidate URL string.

    Returns:
        ``True`` when the URL has a valid scheme and network location,
        ``False`` otherwise.

    Examples:
        >>> validate_url("https://www.aliexpress.com/item/123.html")
        True
        >>> validate_url("not-a-url")
        False
    """
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HTML sanitisation
# ---------------------------------------------------------------------------

# Tags that we strip entirely (along with their content).
_STRIP_TAGS_RE = re.compile(
    r"<(script|style|iframe|object|embed|form|input|button)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)

# Any remaining HTML tags (kept as text after entity-escaping).
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def sanitize_html(text: str) -> str:
    """Strip dangerous HTML tags and return plain-text-safe output.

    The function:
    1. Removes ``<script>``, ``<style>``, ``<iframe>``, ``<object>``,
       ``<embed>``, ``<form>``, ``<input>``, and ``<button>`` elements
       together with their content.
    2. Strips all remaining HTML tags (keeping the inner text).
    3. Unescapes HTML entities so the caller gets readable text.
    4. Collapses excessive whitespace.

    Args:
        text: Raw HTML or text that may contain HTML fragments.

    Returns:
        Sanitised plain-text string.

    Examples:
        >>> sanitize_html("<p>Hello <b>World</b></p>")
        'Hello World'
        >>> sanitize_html('<script>alert("xss")</script>Safe')
        'Safe'
    """
    if not isinstance(text, str):
        return ""

    # 1. Remove dangerous elements entirely
    cleaned = _STRIP_TAGS_RE.sub("", text)

    # 2. Strip remaining HTML tags
    cleaned = _HTML_TAG_RE.sub("", cleaned)

    # 3. Unescape HTML entities
    cleaned = html.unescape(cleaned)

    # 4. Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned
