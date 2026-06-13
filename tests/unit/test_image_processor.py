"""Unit tests for perceptual-hash image similarity (no network, no creds)."""

import io

from PIL import Image

from dropagent.core.image_processor import (
    DEFAULT_HASH_SIZE,
    dhash,
    dhash_from_bytes,
    hamming_distance,
    hash_similarity,
    image_similarity,
    make_image_scorer,
)

BITS = DEFAULT_HASH_SIZE * DEFAULT_HASH_SIZE


def _gradient(*, reverse: bool = False, size: int = 32) -> Image.Image:
    """A horizontal grayscale gradient (left->right brighter, or reversed)."""
    img = Image.new("L", (size, size))
    data = []
    for _y in range(size):
        for x in range(size):
            v = x * 255 // (size - 1)
            data.append(255 - v if reverse else v)
    img.putdata(data)
    return img


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fetcher(mapping: dict[str, bytes | None]):
    async def _fetch(url: str) -> bytes | None:
        return mapping.get(url)

    return _fetch


# --- pure hashing ------------------------------------------------------------


def test_dhash_is_deterministic():
    img = _gradient()
    assert dhash(img) == dhash(img.copy())


def test_identical_hash_similarity_is_one():
    h = dhash(_gradient())
    assert hash_similarity(h, h) == 1.0


def test_opposite_gradients_are_dissimilar():
    h_lr = dhash(_gradient())
    h_rl = dhash(_gradient(reverse=True))
    # Every adjacent comparison flips -> maximal Hamming distance.
    assert hamming_distance(h_lr, h_rl) == BITS
    assert hash_similarity(h_lr, h_rl) == 0.0


def test_hamming_distance_counts_differing_bits():
    assert hamming_distance(0b1010, 0b0011) == 2
    assert hamming_distance(0, 0) == 0


def test_hash_similarity_partial():
    # 16 of 64 bits differ -> 0.75 similarity.
    a = 0
    b = (1 << 16) - 1
    assert hash_similarity(a, b) == 1.0 - 16 / BITS


def test_dhash_from_bytes_roundtrips_png():
    img = _gradient()
    assert dhash_from_bytes(_png_bytes(img)) == dhash(img)


def test_dhash_from_bytes_invalid_returns_none():
    assert dhash_from_bytes(b"definitely not an image") is None


# --- image_similarity (injected fetch) ---------------------------------------


async def test_image_similarity_identical_images():
    png = _png_bytes(_gradient())
    fetch = _fetcher({"a": png, "b": png})
    assert await image_similarity("a", "b", fetch=fetch) == 1.0


async def test_image_similarity_opposite_images():
    fetch = _fetcher({"a": _png_bytes(_gradient()), "b": _png_bytes(_gradient(reverse=True))})
    assert await image_similarity("a", "b", fetch=fetch) == 0.0


async def test_image_similarity_missing_url_is_none():
    fetch = _fetcher({"a": _png_bytes(_gradient())})
    assert await image_similarity("", "a", fetch=fetch) is None
    assert await image_similarity("a", "", fetch=fetch) is None


async def test_image_similarity_fetch_failure_is_none():
    fetch = _fetcher({"a": _png_bytes(_gradient()), "b": None})
    assert await image_similarity("a", "b", fetch=fetch) is None


async def test_image_similarity_undecodable_is_none():
    fetch = _fetcher({"a": _png_bytes(_gradient()), "b": b"garbage"})
    assert await image_similarity("a", "b", fetch=fetch) is None


async def test_make_image_scorer_matches_image_similarity():
    png = _png_bytes(_gradient())
    scorer = make_image_scorer(fetch=_fetcher({"a": png, "b": png}))
    assert await scorer("a", "b") == 1.0
