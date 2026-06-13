"""
Perceptual-hash image similarity for product matching.

Narrows a coarse title/keyword match down to *the same physical product* by
comparing the listing photos that the official Naver Shopping API and the
AliExpress affiliate API already return (no scraping; honours 공식 API 우선).

Uses a dependency-light **dHash** (difference hash) built on Pillow (already a
project dependency) + the stdlib -- no numpy, no model hosting, per the
research's "pHash over CLIP for the deployment budget" call. dHash is robust to
scale/compression and cheap; it is a *re-rank/gate* signal, not a sole verdict.

All network access is injected (``fetch``) so the hashing core is unit-testable
without credentials or a network.
"""

from __future__ import annotations

import io
from collections.abc import Awaitable, Callable

import httpx
from PIL import Image, UnidentifiedImageError

from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# 8x8 difference hash -> 64-bit fingerprint.
DEFAULT_HASH_SIZE = 8

# An async ``url -> image bytes`` fetcher (injected for testability).
ImageFetcher = Callable[[str], Awaitable[bytes | None]]

# An async ``(url_a, url_b) -> similarity|None`` scorer (what ProductMatcher wants).
ImageScorer = Callable[[str, str], Awaitable["float | None"]]


def dhash(image: Image.Image, hash_size: int = DEFAULT_HASH_SIZE) -> int:
    """
    Compute the difference hash of a PIL image as an integer.

    Converts to grayscale, resizes to ``(hash_size + 1, hash_size)``, and sets
    one bit per adjacent horizontal pixel pair (left brighter than right).
    """
    gray = image.convert("L").resize(
        (hash_size + 1, hash_size), Image.Resampling.LANCZOS
    )
    px = gray.load()  # PixelAccess: px[x, y]; avoids deprecated getdata()
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            bits = (bits << 1) | int(px[col, row] > px[col + 1, row])
    return bits


def dhash_from_bytes(data: bytes, hash_size: int = DEFAULT_HASH_SIZE) -> int | None:
    """Decode image bytes and return the dHash, or ``None`` on undecodable input."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            return dhash(img, hash_size)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("image_hash_failed", error=str(exc))
        return None


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two integer hashes."""
    return (a ^ b).bit_count()


def hash_similarity(
    a: int,
    b: int,
    *,
    bits: int = DEFAULT_HASH_SIZE * DEFAULT_HASH_SIZE,
) -> float:
    """Map two hashes to a ``[0, 1]`` similarity (1.0 = identical)."""
    return 1.0 - hamming_distance(a, b) / bits


async def fetch_image_bytes(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> bytes | None:
    """Fetch image bytes from ``url``; returns ``None`` on any error / non-200."""
    if not url:
        return None
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("image_fetch_non_200", url=url, status_code=resp.status_code)
            return None
        return resp.content
    except httpx.HTTPError as exc:
        logger.warning("image_fetch_failed", url=url, error=str(exc))
        return None
    finally:
        if owns_client:
            await client.aclose()


async def image_similarity(
    url_a: str,
    url_b: str,
    *,
    fetch: ImageFetcher = fetch_image_bytes,
    hash_size: int = DEFAULT_HASH_SIZE,
) -> float | None:
    """
    Perceptual similarity (0..1) between two images by URL.

    Returns ``None`` when either URL is missing, a fetch fails, or an image
    cannot be decoded -- so callers can fall back to title similarity rather
    than treat a fetch error as "different".
    """
    if not url_a or not url_b:
        return None
    a_bytes = await fetch(url_a)
    b_bytes = await fetch(url_b)
    if a_bytes is None or b_bytes is None:
        return None
    hash_a = dhash_from_bytes(a_bytes, hash_size)
    hash_b = dhash_from_bytes(b_bytes, hash_size)
    if hash_a is None or hash_b is None:
        return None
    return hash_similarity(hash_a, hash_b, bits=hash_size * hash_size)


def make_image_scorer(
    *,
    fetch: ImageFetcher = fetch_image_bytes,
    hash_size: int = DEFAULT_HASH_SIZE,
) -> ImageScorer:
    """
    Build an ``(url_a, url_b) -> similarity|None`` scorer for ``ProductMatcher``.

    Hashes are cached per scorer instance keyed by URL, so the (constant) Naver
    image and any repeated AliExpress image are fetched + hashed only once per
    matching run rather than once per candidate comparison.
    """
    cache: dict[str, int | None] = {}

    async def _hash(url: str) -> int | None:
        if url in cache:
            return cache[url]
        data = await fetch(url)
        digest = dhash_from_bytes(data, hash_size) if data is not None else None
        cache[url] = digest
        return digest

    async def _scorer(url_a: str, url_b: str) -> float | None:
        if not url_a or not url_b:
            return None
        hash_a = await _hash(url_a)
        hash_b = await _hash(url_b)
        if hash_a is None or hash_b is None:
            return None
        return hash_similarity(hash_a, hash_b, bits=hash_size * hash_size)

    return _scorer
